import re

from pydantic import BaseModel

from app.modeling.graph_schema import GraphSchema
from app.utils.logger import get_logger

logger = get_logger("query.query_validator")


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []


class QueryValidator:
    def __init__(self, schema: GraphSchema) -> None:
        self.schema = schema
        self._valid_labels = {n.label.lower(): n.label for n in schema.nodes}
        self._valid_edge_types = {e.type.lower(): e.type for e in schema.edges}
        # Build connectivity map: rel_type -> set of (from_label, to_label) pairs
        self._rel_connectivity: dict[str, set[tuple[str, str]]] = {}
        for e in schema.edges:
            self._rel_connectivity.setdefault(e.type.lower(), set()).add(
                (e.from_node.lower(), e.to_node.lower())
            )

    def validate(self, cypher: str) -> ValidationResult:
        """Validate Cypher against the known graph schema."""
        errors: list[str] = []

        # Check for variable name conflicts (same name for node and relationship)
        node_vars = set(re.findall(r"(?<!\w)\((\w+)(?::`?\w+`?)?(?:\s*\{[^}]*\})?\)", cypher))
        rel_vars = set(re.findall(r"\[(\w+):", cypher))
        conflicts = node_vars & rel_vars
        if conflicts:
            errors.append(
                f"Variable name conflict — used for both node and relationship: {conflicts}. "
                f"Use unique names (e.g. nodes: c, o, d; relationships: r, r1, r2)."
            )
        self._check_variable_relabeling(cypher, errors)

        # Extract node labels used in the query (backtick-quoted or plain)
        label_patterns = re.findall(r":`?(\w+)`?", cypher)
        for label in label_patterns:
            if label.lower() not in self._valid_labels and label.lower() not in self._valid_edge_types:
                errors.append(f"Unknown label or relationship type: '{label}'")

        # Extract relationship types from -[r:TYPE]-> patterns
        rel_patterns = re.findall(r"\[(?:\w+)?:`?(\w+)`?\]", cypher)
        for rel in rel_patterns:
            if rel.lower() not in self._valid_edge_types:
                errors.append(f"Unknown relationship type: '{rel}'")

        # Syntax sanity checks for common malformed LLM outputs
        self._check_malformed_patterns(cypher, errors)

        # Relationship connectivity validation
        self._check_relationship_connectivity(cypher, errors)

        # Property validation (soft warning — no hard error)
        self._check_properties(cypher)

        if errors:
            logger.warning("Cypher validation failed: %s", errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    @staticmethod
    def _check_malformed_patterns(cypher: str, errors: list[str]) -> None:
        """Catch malformed patterns that should be rejected before execution."""
        if re.search(r"-\[(?:\w+)?:`?\w+`?\]\s*<-", cypher):
            errors.append(
                "Invalid relationship arrow syntax '-[:REL]<-'. "
                "Use '<-[:REL]-' or '-[:REL]->'."
            )
        if re.search(r"\{[^{}]*\bOR\b[^{}]*\}", cypher, flags=re.IGNORECASE):
            errors.append(
                "Invalid inline map predicate with OR. "
                "Map literals cannot contain OR; move OR conditions to a WHERE clause."
            )
        for with_clause in re.findall(r"\bWITH\b([^\n\r;]*)", cypher, flags=re.IGNORECASE):
            if re.search(r"\)\s*-\[(?:\w+:)?`?\w+`?\]\s*(?:->|<-)\s*\(", with_clause):
                errors.append(
                    "Invalid relationship pattern inside WITH clause. "
                    "Use MATCH/OPTIONAL MATCH for path patterns, and keep WITH for variable projection only."
                )
                break
        # Neo4j pattern expressions in WHERE cannot introduce new variables like (p2:`Payment`)
        where_match = re.search(
            r"\bWHERE\b(?P<body>[\s\S]*?)(?:\bRETURN\b|\bWITH\b|\bORDER\s+BY\b|\bLIMIT\b|$)",
            cypher,
            flags=re.IGNORECASE,
        )
        if where_match and re.search(
            r"\(\w+\s*:\s*`?\w+`?\)",
            where_match.group("body"),
        ) and not re.search(
            r"\bEXISTS\s*\{\s*MATCH\b",
            where_match.group("body"),
            flags=re.IGNORECASE,
        ) and not re.search(
            r"\bMATCH\b",
            where_match.group("body"),
            flags=re.IGNORECASE,
        ):
            errors.append(
                "Invalid pattern expression in WHERE introduces a labeled variable. "
                "Use EXISTS { MATCH ... } or OPTIONAL MATCH + IS NULL instead."
            )

    @staticmethod
    def _check_variable_relabeling(cypher: str, errors: list[str]) -> None:
        """Block reusing one variable name with multiple labels (e.g. p:Product then p:Payment)."""
        bindings: dict[str, str] = {}
        for var, label in re.findall(r"\((\w+):`?(\w+)`?(?:\s*\{[^}]*\})?\)", cypher):
            prev = bindings.get(var)
            if prev and prev.lower() != label.lower():
                errors.append(
                    f"Variable '{var}' is reused with multiple labels ({prev}, {label}). "
                    "Use distinct variable names per label."
                )
                return
            bindings[var] = label

    def _check_relationship_connectivity(self, cypher: str, errors: list[str]) -> None:
        """Check that relationships connect the correct node types per schema.

        Detects errors like (Product)-[:PLACED_ORDER]->(Customer) when PLACED_ORDER
        only connects Customer->SalesOrder.
        """
        # Build variable → label bindings: (var:`Label`)
        var_labels: dict[str, str] = {}
        for var, label in re.findall(r"\((\w+):`?(\w+)`?(?:\s*\{[^}]*\})?\)", cypher):
            var_labels[var] = label.lower()

        # Use lookahead to capture overlapping triples in chained paths.
        forward = [
            (m.group(1), m.group(2), m.group(3))
            for m in re.finditer(
                r"(?=\((\w+)(?::`?\w+`?)?(?:\s*\{[^}]*\})?\)\s*-\[(?:\w+)?:`?(\w+)`?\]\s*->\s*\((\w+)(?::`?\w+`?)?(?:\s*\{[^}]*\})?\))",
                cypher,
            )
        ]
        reverse = [
            (m.group(1), m.group(2), m.group(3))
            for m in re.finditer(
                r"(?=\((\w+)(?::`?\w+`?)?(?:\s*\{[^}]*\})?\)\s*<-\[(?:\w+)?:`?(\w+)`?\]\s*-\s*\((\w+)(?::`?\w+`?)?(?:\s*\{[^}]*\})?\))",
                cypher,
            )
        ]

        for src_var, rel_type, tgt_var in forward:
            src_label = var_labels.get(src_var)
            tgt_label = var_labels.get(tgt_var)
            if not src_label or not tgt_label:
                continue
            valid_pairs = self._rel_connectivity.get(rel_type.lower(), set())
            # Forward arrow: src-[:REL]->tgt means schema should have src->tgt
            if (src_label, tgt_label) not in valid_pairs:
                src_canon = self._canon(src_label)
                tgt_canon = self._canon(tgt_label)
                # Check if it's just reversed
                if (tgt_label, src_label) in valid_pairs:
                    errors.append(
                        f"Wrong direction: ({src_canon})-[:{rel_type}]->({tgt_canon}) "
                        f"— {rel_type} goes from {tgt_canon} to {src_canon}. "
                        f"Use <-[:{rel_type}]- instead of -[:{rel_type}]->"
                    )
                else:
                    errors.append(
                        f"Relationship {rel_type} does not connect "
                        f"{src_canon} to {tgt_canon}. "
                        f"Check the schema for valid connections."
                    )

        for src_var, rel_type, tgt_var in reverse:
            src_label = var_labels.get(src_var)
            tgt_label = var_labels.get(tgt_var)
            if not src_label or not tgt_label:
                continue
            valid_pairs = self._rel_connectivity.get(rel_type.lower(), set())
            # Reverse arrow: src<-[:REL]-tgt means schema should have tgt->src
            if (tgt_label, src_label) not in valid_pairs:
                if (src_label, tgt_label) in valid_pairs:
                    errors.append(
                        f"Wrong direction: reverse arrow used but {rel_type} goes from "
                        f"{self._canon(src_label)} to {self._canon(tgt_label)}. "
                        f"Use -[:{rel_type}]-> instead of <-[:{rel_type}]-"
                    )
                else:
                    errors.append(
                        f"Relationship {rel_type} does not connect "
                        f"{self._canon(tgt_label)} to {self._canon(src_label)}. "
                        f"Check the schema for valid connections."
                    )

    def _canon(self, label_lower: str) -> str:
        """Return the canonical (original-case) label name."""
        return self._valid_labels.get(label_lower, label_lower)

    def _check_properties(self, cypher: str) -> None:
        """Soft-check that property accesses reference known node properties.

        Logs debug warnings but does NOT produce hard errors, since relationship
        properties and Cypher built-in functions can look like property access.
        """
        # Build variable → label bindings from MATCH patterns: (var:`Label`)
        var_labels: dict[str, str] = {}
        for var, label in re.findall(r"\((\w+):`?(\w+)`?(?:\s*\{[^}]*\})?\)", cypher):
            var_labels[var] = label

        # Find property accesses: var.`prop` or var.prop
        prop_accesses = re.findall(r"(\w+)\.`?(\w+)`?", cypher)
        for var, prop in prop_accesses:
            label = var_labels.get(var)
            if not label:
                continue
            node = self.schema.get_node(label)
            if not node:
                continue
            if prop not in node.properties:
                logger.debug(
                    "Property '%s' not found on node %s (used as %s.%s) — may be a relationship property",
                    prop, label, var, prop,
                )
