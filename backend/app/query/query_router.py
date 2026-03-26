import re
from typing import Any

from pydantic import BaseModel

from app.config.constants import ALTERNATE_ID_FIELDS, PREFERRED_DISTINCT_FIELDS
from app.llm.cypher_generator import CypherGenerator
from app.llm.guardrails import Guardrails, GuardrailResult
from app.llm.intent_extractor import IntentExtractor, QueryIntent
from app.llm.prompt_manager import PromptManager
from app.llm.template_registry import QueryTemplateRegistry
from app.modeling.graph_schema import GraphSchema
from app.query.query_validator import QueryValidator
from app.utils.logger import get_logger

logger = get_logger("query.query_router")


class RoutedQuery(BaseModel):
    cypher: str
    intent: QueryIntent
    template_name: str
    parameters: dict


class QueryRoutingError(Exception):
    """Raised when the query cannot be routed through the pipeline."""

    def __init__(self, message: str, stage: str, details: Any = None):
        self.stage = stage
        self.details = details
        super().__init__(message)


class QueryRouter:
    def __init__(
        self,
        guardrails: Guardrails,
        intent_extractor: IntentExtractor,
        template_registry: QueryTemplateRegistry,
        cypher_generator: CypherGenerator,
        validator: QueryValidator,
        schema: GraphSchema,
        llm_client: Any = None,
        llm_model: str = "",
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.guardrails = guardrails
        self.intent_extractor = intent_extractor
        self.template_registry = template_registry
        self.cypher_generator = cypher_generator
        self.validator = validator
        self.schema = schema
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.prompt_manager = prompt_manager

    def route(self, user_query: str) -> RoutedQuery:
        """Route a user query through the full pipeline.

        Steps:
        1. Input guardrail
        2. Intent extraction (LLM)
        3. Domain guardrail
        4. Template selection
        5. Parameter mapping
        6. Cypher generation
        7. Output guardrail
        8. Schema validation
        """
        # 1. Input guardrail
        input_check = self.guardrails.validate_input(user_query)
        if not input_check.passed:
            raise QueryRoutingError(
                input_check.reason or "Input validation failed",
                stage="input_guardrail",
                details=input_check,
            )

        # 2. Intent extraction
        intent = self.intent_extractor.extract(user_query, self.schema)
        logger.info(
            "Extracted intent: type=%s, entities=%s, confidence=%.2f",
            intent.intent_type, intent.entities, intent.confidence,
        )

        # 3. Domain guardrail
        domain_check = self.guardrails.validate_domain(intent.entities)
        if not domain_check.passed:
            raise QueryRoutingError(
                domain_check.reason or "Domain validation failed",
                stage="domain_guardrail",
                details=domain_check,
            )

        # 3b. Force DISTINCT intent when trigger words are present
        query_words = set(user_query.lower().split())
        if (
            query_words & self._DISTINCT_KEYWORDS
            and intent.intent_type in ("list_neighbors", "find_node", "search", "aggregate")
            and intent.entities
        ):
            logger.info(
                "Redirecting %s → distinct (distinct keywords detected in query)",
                intent.intent_type,
            )
            intent.intent_type = "distinct"

        # 3c. Auto-redirect to custom if find_node uses a property that doesn't exist on the entity
        if intent.intent_type == "find_node" and intent.entities and intent.filters:
            node = self.schema.get_node(intent.entities[0])
            if node:
                filter_key = next(iter(intent.filters), "")
                if filter_key and filter_key not in node.properties:
                    logger.info(
                        "Redirecting find_node → custom: property '%s' not on %s",
                        filter_key, intent.entities[0],
                    )
                    intent.intent_type = "custom"

        # 3d. Rank queries with multi-hop constraints should use custom generation
        if intent.intent_type == "rank" and self._requires_custom_rank(intent):
            logger.info("Redirecting rank → custom (requires multi-hop/path-aware query)")
            intent.intent_type = "custom"

        # 4. Custom intent → deterministic template or LLM-generated Cypher
        deterministic_custom = self._select_custom_template(intent)
        if intent.intent_type == "custom" and not deterministic_custom:
            cypher = self._generate_custom_cypher_with_retry(user_query, intent.entities, intent.filters)
            template_name = "custom"
            parameters = {}
        else:
            # 4a. Template selection
            template = deterministic_custom or self.template_registry.select_template(intent)

            # 4b. Template corrections — redirect misclassified intents
            template = self._correct_template(intent, template)
            logger.info("Selected template: %s", template.name)

            # 5. Parameter mapping
            parameters = self._map_parameters(intent, template)
            logger.info("Mapped parameters: %s", parameters)

            # 6. Cypher generation
            cypher = self.cypher_generator.generate(template, parameters)
            template_name = template.name

        logger.info("Generated Cypher: %s", cypher)

        # 7. Output guardrail
        output_check = self.guardrails.validate_output(cypher)
        if not output_check.passed:
            raise QueryRoutingError(
                output_check.reason or "Output validation failed",
                stage="output_guardrail",
                details=output_check,
            )

        # 8. Schema validation
        validation = self.validator.validate(cypher)
        if not validation.valid:
            raise QueryRoutingError(
                f"Schema validation failed: {validation.errors}",
                stage="schema_validation",
                details=validation,
            )

        return RoutedQuery(
            cypher=cypher,
            intent=intent,
            template_name=template_name,
            parameters=parameters,
        )

    def _generate_custom_cypher(
        self,
        user_query: str,
        seed_labels: list[str] | None = None,
        intent_filters: dict | None = None,
    ) -> str:
        """Generate Cypher via LLM for complex queries that don't fit templates."""
        if not self.llm_client or not self.prompt_manager:
            raise QueryRoutingError(
                "LLM client not configured for custom Cypher generation",
                stage="custom_cypher",
            )

        relevant_schema = self.schema.extract_relevant_subschema(seed_labels or [])
        candidate_paths = self.schema.find_candidate_path_patterns(seed_labels or [])
        edge_details = []
        for e in relevant_schema.edges:
            detail = f"(:{e.from_node})-[:{e.type}]->(:{e.to_node})"
            if e.rel_properties:
                detail += f"  rel props: {', '.join(e.rel_properties)}"
            edge_details.append(detail)

        prompt = self.prompt_manager.render("cypher_generation", {
            "node_properties": "\n".join(relevant_schema.node_properties_summary(max_properties_per_node=8)),
            "edge_details": "\n".join(edge_details),
            "candidate_paths": "\n".join(candidate_paths),
            "intent_hints": "\n".join(
                f"- {k}: {v}" for k, v in (intent_filters or {}).items()
            ),
            "user_query": user_query,
        })

        logger.debug("Custom Cypher prompt (model=%s):\n%s", self.llm_model, prompt)

        response = self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout=30,
        )

        content = response.choices[0].message.content
        if not content:
            raise QueryRoutingError(
                "LLM returned empty response for custom Cypher generation",
                stage="custom_cypher",
            )
        cypher = content.strip()
        # Strip markdown code fences if present
        if cypher.startswith("```"):
            lines = cypher.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cypher = "\n".join(lines).strip()

        logger.info("LLM-generated custom Cypher: %s", cypher)
        return cypher

    @staticmethod
    def _fix_arrow_syntax(cypher: str) -> str:
        """Fix common LLM mistake: )-[:REL]<-( is invalid; correct is )<-[:REL]-(."""
        import re
        # Fix: (x)-[:REL]<-(y) → (x)<-[:REL]-(y)
        cypher = re.sub(
            r"\)\s*-(\[(?:\w+)?:`?\w+`?\])\s*<-\s*\(",
            r")<-\1-(",
            cypher,
        )
        # Fix: (x)->[:REL]-(y) → (x)-[:REL]->(y)  (less common but possible)
        cypher = re.sub(
            r"\)\s*->(\[(?:\w+)?:`?\w+`?\])\s*-\s*\(",
            r")-\1->(",
            cypher,
        )
        return cypher

    @staticmethod
    def _fix_inline_or_maps(cypher: str) -> str:
        """Rewrite invalid inline map OR predicates into WHERE clauses.

        Example:
        (p:`Product` {`product`: 'X' OR `productOldId`: 'X'})
        ->
        (p:`Product`) WHERE (p.`product` = 'X' OR p.`productOldId` = 'X')
        """
        import re

        conditions: list[str] = []

        pattern = re.compile(
            r"\((\w+):`?(\w+)`?\s*\{\s*`?(\w+)`?\s*:\s*'([^']*)'\s+OR\s+`?(\w+)`?\s*:\s*'([^']*)'\s*\}\)"
        )

        def _replace(match: re.Match[str]) -> str:
            var, label, p1, v1, p2, v2 = match.groups()
            conditions.append(f"({var}.`{p1}` = '{v1}' OR {var}.`{p2}` = '{v2}')")
            return f"({var}:`{label}`)"

        rewritten = pattern.sub(_replace, cypher)
        if not conditions:
            return cypher

        injected = " AND ".join(conditions)
        if " WHERE " in rewritten:
            return rewritten.replace(" WHERE ", f" WHERE {injected} AND ", 1)
        if "\nWHERE " in rewritten:
            return rewritten.replace("\nWHERE ", f"\nWHERE {injected} AND ", 1)
        if "\nRETURN " in rewritten:
            return rewritten.replace("\nRETURN ", f"\nWHERE {injected}\nRETURN ", 1)
        if " RETURN " in rewritten:
            return rewritten.replace(" RETURN ", f" WHERE {injected} RETURN ", 1)
        return f"{rewritten}\nWHERE {injected}"

    @staticmethod
    def _fix_exists_match_syntax(cypher: str) -> str:
        """Rewrite invalid NOT EXISTS (MATCH ...) into Neo4j EXISTS { MATCH ... } form."""
        import re
        cypher = re.sub(
            r"NOT\s+EXISTS\s*\(\s*MATCH\s+([^)]+)\)",
            r"NOT EXISTS { MATCH \1 }",
            cypher,
            flags=re.IGNORECASE,
        )
        return cypher

    @staticmethod
    def _fix_with_path_expressions(cypher: str) -> str:
        """Move relationship path expressions out of WITH into MATCH clauses.

        Example invalid:
          WITH i, so-[:CONTAINS]->(p:Product)
        Rewritten:
          WITH i
          MATCH (so)-[:CONTAINS]->(p:Product)
        """
        rel_pattern = re.compile(
            r"(\)\s*-(?:\[[^\]]+\])\s*(?:->|<-)\s*\()|(\b\w+\s*-(?:\[[^\]]+\])\s*(?:->|<-)\s*\()"
        )

        rewritten_lines: list[str] = []
        for raw_line in cypher.splitlines():
            line = raw_line.strip()
            if not re.match(r"^WITH\b", line, flags=re.IGNORECASE):
                rewritten_lines.append(raw_line)
                continue

            with_body = re.sub(r"^WITH\s+", "", line, flags=re.IGNORECASE)
            parts = [p.strip() for p in with_body.split(",") if p.strip()]

            with_items: list[str] = []
            match_items: list[str] = []
            for item in parts:
                if rel_pattern.search(item):
                    normalized = item
                    # Ensure the path expression starts with a node pattern.
                    if re.match(r"^\w+\s*-\[", normalized):
                        normalized = re.sub(r"^(\w+)\s*-\[", r"(\1)-[", normalized, count=1)
                    elif not normalized.startswith("("):
                        normalized = f"({normalized}"
                    match_items.append(normalized)
                else:
                    with_items.append(item)

            if with_items:
                rewritten_lines.append(f"WITH {', '.join(with_items)}")

            for match_item in match_items:
                rewritten_lines.append(f"MATCH {match_item}")

        return "\n".join(rewritten_lines)

    def _generate_custom_cypher_with_retry(
        self,
        user_query: str,
        seed_labels: list[str] | None = None,
        intent_filters: dict | None = None,
        max_retries: int = 2,
    ) -> str:
        """Generate custom Cypher with validation-based retry loop."""
        cypher = self._generate_custom_cypher(user_query, seed_labels, intent_filters)
        cypher = self._fix_arrow_syntax(cypher)
        cypher = self._fix_inline_or_maps(cypher)
        cypher = self._fix_exists_match_syntax(cypher)
        cypher = self._fix_with_path_expressions(cypher)

        # Pre-compute candidate paths for retry context
        candidate_paths = self.schema.find_candidate_path_patterns(seed_labels or [])
        paths_hint = "\n".join(candidate_paths)

        for attempt in range(max_retries):
            validation = self.validator.validate(cypher)
            if validation.valid:
                return cypher

            logger.warning(
                "Custom Cypher validation failed (attempt %d/%d): %s",
                attempt + 1, max_retries, validation.errors,
            )

            # Ask LLM to fix the errors — include candidate paths for context
            if not self.llm_client or not self.prompt_manager:
                break

            fix_prompt = (
                f"The following Cypher query has errors:\n\n{cypher}\n\n"
                f"Errors:\n" + "\n".join(f"- {e}" for e in validation.errors) + "\n\n"
                f"Valid traversal patterns (COPY these exactly):\n{paths_hint}\n\n"
                f"Intent hints to preserve:\n"
                + "\n".join(f"- {k}: {v}" for k, v in (intent_filters or {}).items()) + "\n\n"
                f"IMPORTANT: Arrow direction matters. Reverse traversal uses <-[:REL]- NOT -[:REL]<-\n"
                f"Example: (p:`Product`)<-[:CONTAINS]-(so:`SalesOrder`)\n\n"
                f"IMPORTANT: For multi-step constraints, build with multiple MATCH/OPTIONAL MATCH clauses, "
                f"not one chained path that invents direct links.\n"
                f"Use this skeleton when relevant:\n"
                f"MATCH (c:`Customer`)-[:PLACED_ORDER]->(o:`SalesOrder`)-[:CONTAINS]->(p:`Product`)\n"
                f"MATCH (d:`Delivery`)-[:FULFILLS]->(o)\n"
                f"OPTIONAL MATCH (:Payment)-[:PAID_BY]->(c)\n"
                f"WHERE (p.`product` = '<identifier>' OR p.`productOldId` = '<identifier>') "
                f"AND <payment missing condition>\n"
                f"For payment absence, use one of:\n"
                f"  WHERE NOT EXISTS {{ MATCH (:Payment)-[:PAID_BY]->(c) }}\n"
                f"  OR OPTIONAL MATCH (:Payment)-[:PAID_BY]->(c) ... WHERE paymentVar IS NULL\n\n"
                f"Fix the query and respond with ONLY the corrected Cypher. No explanation, no markdown fences."
            )

            try:
                response = self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{"role": "user", "content": fix_prompt}],
                    temperature=0.0,
                    timeout=30,
                )
                content = response.choices[0].message.content
                if not content:
                    logger.warning("LLM retry returned empty response")
                    break
                cypher = content.strip()
                if cypher.startswith("```"):
                    lines = cypher.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    cypher = "\n".join(lines).strip()
                cypher = self._fix_arrow_syntax(cypher)
                cypher = self._fix_inline_or_maps(cypher)
                cypher = self._fix_exists_match_syntax(cypher)
                cypher = self._fix_with_path_expressions(cypher)
                logger.info("Retried custom Cypher (attempt %d): %s", attempt + 1, cypher)
            except Exception as e:
                logger.warning("LLM retry failed: %s", e)
                break

        return cypher

    _RANKING_KEYWORDS = {"most", "highest", "lowest", "least", "top", "fewest", "ranked", "ranking"}
    _DISTINCT_KEYWORDS = {"types", "kinds", "different", "unique", "categories", "distinct"}

    def _requires_custom_rank(self, intent: QueryIntent) -> bool:
        """Detect rank intents that cannot be answered by the direct rank template."""
        if intent.intent_type != "rank" or len(intent.entities) < 2:
            return False

        # Covered by deterministic template.
        if self._is_delivered_division_rank(intent):
            return False

        # Filters like delivery_status/division imply multi-hop context and extra predicates.
        if {"delivery_status", "division"} & set(intent.filters.keys()):
            return True

        src = intent.entities[0]
        tgt = intent.entities[1]
        rel = str(intent.filters.get("relationship_type", "")).upper()

        # Direct rank template only supports direct relationships between source and target.
        for edge in self.schema.edges:
            if rel and edge.type.upper() != rel:
                continue
            if (
                (edge.from_node == src and edge.to_node == tgt)
                or (edge.from_node == tgt and edge.to_node == src)
            ):
                return False

        return True

    @staticmethod
    def _is_delivered_division_rank(intent: QueryIntent) -> bool:
        entities = set(intent.entities)
        filters = intent.filters
        has_division = bool(filters.get("division"))
        has_delivery = str(filters.get("delivery_status", "")).lower() in {"delivered", "delivery", "shipped"}
        return {"Plant", "Product"} <= entities and has_division and has_delivery

    def _select_custom_template(self, intent: QueryIntent):
        """Select deterministic template for common custom intents when possible."""
        if self._is_delivered_division_rank(intent):
            try:
                return self.template_registry.get_template("rank_delivered_by_division")
            except KeyError:
                pass

        query_text = f"{intent.raw_query} {intent.filters.get('description', '')}".lower()
        entities = set(intent.entities)
        has_product = "product" in query_text and "Product" in entities
        has_customer = "customer" in query_text and "Customer" in entities
        has_delivery = "deliver" in query_text and "Delivery" in entities
        has_unpaid = ("no payment" in query_text or "unpaid" in query_text or "without payment" in query_text)
        has_payment = "payment" in query_text and "Payment" in entities
        has_journal = "journal" in query_text and "JournalEntry" in entities
        has_invoice = "invoice" in query_text and "Invoice" in entities

        if has_product and has_customer and has_delivery and has_unpaid:
            try:
                return self.template_registry.get_template("customers_ordered_delivered_unpaid")
            except KeyError:
                pass
        if has_product and has_payment and has_journal and has_invoice:
            try:
                return self.template_registry.get_template("payments_for_product_invoice_journal")
            except KeyError:
                pass
        return None

    @staticmethod
    def _build_identifier_where(var: str, label: str, property_name: str, value: str) -> str:
        """Build a WHERE clause that matches against the primary key AND alternate identifiers.

        Returns e.g.: n.`product` = 'X' OR n.`productOldId` = 'X'
        """
        safe_value = value.replace("'", "''")
        clauses = [f"{var}.`{property_name}` = '{safe_value}'"]

        alt_fields = ALTERNATE_ID_FIELDS.get(label, [])
        for alt in alt_fields:
            if alt != property_name:
                clauses.append(f"{var}.`{alt}` = '{safe_value}'")

        return " OR ".join(clauses)

    def _correct_template(self, intent: QueryIntent, template):
        """Redirect misclassified intents to the correct template."""
        query_words = set(intent.raw_query.lower().split())
        has_ranking_language = bool(query_words & self._RANKING_KEYWORDS)

        # aggregate/count with ranking language → rank
        if template.name in ("aggregate", "count") and has_ranking_language:
            try:
                logger.info("Redirecting %s → rank (ranking language detected in query)", template.name)
                return self.template_registry.get_template("rank")
            except KeyError:
                pass

        # aggregate with no property but 2+ entities → rank
        if template.name == "aggregate" and not intent.filters.get("property_name") and len(intent.entities) >= 2:
            try:
                logger.info("Redirecting aggregate → rank (no property, multiple entities)")
                return self.template_registry.get_template("rank")
            except KeyError:
                pass

        # aggregate with no property and 1 entity → count
        if template.name == "aggregate" and not intent.filters.get("property_name"):
            try:
                logger.info("Redirecting aggregate → count (no property to aggregate)")
                return self.template_registry.get_template("count")
            except KeyError:
                pass

        return template

    def _map_parameters(self, intent: QueryIntent, template) -> dict:
        """Map intent fields to template parameters."""
        params: dict[str, Any] = {}
        filters = intent.filters
        entities = intent.entities

        if template.name == "count":
            params["label"] = entities[0] if entities else ""

        elif template.name == "find_node":
            label = entities[0] if entities else ""
            params["label"] = label
            if filters:
                key = next(iter(filters))
                value = str(filters[key])
                params["where_clause"] = self._build_identifier_where("n", label, key, value)
            else:
                params["where_clause"] = "true"

        elif template.name == "find_path":
            params["start_label"] = entities[0] if len(entities) > 0 else ""
            params["end_label"] = entities[1] if len(entities) > 1 else ""
            params["start_property"] = str(filters.get("start_property", ""))
            params["start_value"] = str(filters.get("start_value", ""))
            params["end_property"] = str(filters.get("end_property", ""))
            params["end_value"] = str(filters.get("end_value", ""))

        elif template.name == "list_neighbors":
            label = entities[0] if entities else ""
            params["label"] = label
            if filters:
                key = next(iter(filters))
                value = str(filters[key])
                params["where_clause"] = self._build_identifier_where("n", label, key, value)
            else:
                params["where_clause"] = "true"

        elif template.name == "aggregate":
            params["label"] = entities[0] if entities else ""
            params["aggregate_function"] = str(filters.get("aggregate_function", "SUM"))
            params["property_name"] = str(filters.get("property_name", ""))

        elif template.name == "find_unlinked":
            params["label"] = entities[0] if entities else ""
            params["relationship_type"] = str(filters.get("relationship_type", ""))
            params["target_label"] = str(filters.get("target_label", entities[1] if len(entities) > 1 else ""))

        elif template.name == "flow_gaps":
            pass  # No parameters needed — fixed analytical query

        elif template.name == "rank":
            params["label"] = entities[0] if entities else ""
            params["relationship_type"] = str(filters.get("relationship_type", "CONTAINS"))
            params["target_label"] = str(filters.get("target_label", entities[1] if len(entities) > 1 else ""))

        elif template.name == "rank_delivered_by_division":
            params["division_value"] = str(filters.get("division", ""))

        elif template.name == "customers_ordered_delivered_unpaid":
            # Prefer explicit product IDs from filters; fallback to first token resembling an id.
            raw = (
                str(filters.get("value", ""))
                or str(filters.get("product", ""))
                or str(filters.get("search_value", ""))
            )
            if not raw:
                for token in intent.raw_query.replace("?", " ").split():
                    if token.upper().startswith("ABC-") or token.upper().startswith("S") or token.isdigit():
                        raw = token
                        break
            params["product_identifier"] = raw

        elif template.name == "payments_for_product_invoice_journal":
            raw = (
                str(filters.get("value", ""))
                or str(filters.get("product", ""))
                or str(filters.get("search_value", ""))
            )
            if not raw:
                for token in intent.raw_query.replace("?", " ").split():
                    if token.upper().startswith("ABC-") or token.upper().startswith("S") or token.isdigit():
                        raw = token
                        break
            params["product_identifier"] = raw

        elif template.name == "find_latest":
            params["label"] = entities[0] if entities else "SalesOrder"
            params["order_property"] = str(filters.get("order_property", "creationDate"))
            params["order_direction"] = str(filters.get("order_direction", "DESC"))

        elif template.name == "distinct":
            params["label"] = entities[0] if entities else ""
            params["property_name"] = str(filters.get("property_name", ""))

            # Smart property selection: if empty or is an ID field, use preferred fields
            label = params["label"]
            node = self.schema.get_node(label) if label else None
            if node:
                is_id = params["property_name"] in node.id_fields
                if not params["property_name"] or is_id:
                    preferred = PREFERRED_DISTINCT_FIELDS.get(label, [])
                    for field in preferred:
                        if field in node.properties:
                            params["property_name"] = field
                            break
                    # Fallback: first non-ID, non-date, non-bool string property
                    if not params["property_name"] or is_id:
                        skip = set(node.id_fields) | {"creationDate", "lastChangeDate", "lastChangeDateTime", "createdByUser"}
                        for prop, dtype in node.properties.items():
                            if prop not in skip and dtype == "object":
                                params["property_name"] = prop
                                break

        elif template.name == "search":
            params["label"] = entities[0] if entities else ""
            params["search_value"] = str(filters.get("search_value", ""))

        return params
