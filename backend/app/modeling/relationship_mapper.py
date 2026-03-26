import json
import re
from pathlib import Path

import pandas as pd

from app.config.constants import CORE_ENTITIES, USE_SCHEMA_INFERENCE
from app.ingestion.schema_inference import CandidateJoin
from app.modeling.graph_schema import EdgeSchema, GraphSchema, NodeSchema
from app.utils.helpers import sanitize_label
from app.utils.logger import get_logger

logger = get_logger("modeling.relationship_mapper")

# Default minimum confidence to accept a candidate join
_DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Fields that commonly match across unrelated entities (false-positive prone)
_GENERIC_FIELDS = {
    "companyCode",
    "creationDate",
    "lastChangeDate",
    "lastChangeDateTime",
    "createdByUser",
    "transactionCurrency",
    "correspondenceLanguage",
    "organizationDivision",
    "distributionChannel",
    "salesOrganization",
    # Postal / contact fields that coincidentally overlap with numeric IDs
    "poBoxPostalCode",
    "postalCode",
    "accountingClerkFaxNumber",
    "accountingClerkPhoneNumber",
    # Boolean / flag fields
    "poBoxIsWithoutNumber",
    "billingIsBlockedForCustomer",
    "businessPartnerIsBlocked",
    "isMarkedForArchiving",
    # Address fields
    "addressId",
    "addressUuid",
}

# Default path for externalized bridge table config
_BRIDGE_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "bridge_tables.json"


class RelationshipMapper:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path
        self._schema: GraphSchema | None = None

    # ------------------------------------------------------------------
    # Node building
    # ------------------------------------------------------------------

    def _build_node_schema(
        self,
        entity_name: str,
        df: pd.DataFrame,
        id_columns: list[str],
    ) -> NodeSchema:
        """Build a NodeSchema for one entity."""
        label = sanitize_label(entity_name)

        # Pick the primary ID: prefer the column whose name closely matches the entity
        primary_id = self._pick_primary_id(entity_name, id_columns, df)

        # Check if primary ID is unique enough; if not, build a composite key
        id_field = self._ensure_unique_id(primary_id, id_columns, df)

        properties = {col: str(dtype) for col, dtype in df.dtypes.items()}

        return NodeSchema(label=label, source_entity=entity_name, properties=properties, id_field=id_field)

    @staticmethod
    def _pick_primary_id(entity_name: str, id_columns: list[str], df: pd.DataFrame) -> str:
        """Heuristic: choose the ID column most closely related to the entity name."""
        if not id_columns:
            return df.columns[0]

        # Normalise entity name tokens for matching
        # e.g. "sales_order_headers" -> {"sales", "order", "header"}
        tokens = set(entity_name.lower().split("_"))
        # Add singular forms
        singulars = {t.rstrip("s") for t in tokens if t.endswith("s")}
        tokens |= singulars

        best_col = id_columns[0]
        best_score = -1
        for col in id_columns:
            col_lower = col.lower()
            # Exact match with a token wins immediately
            if col_lower in tokens or col_lower.rstrip("s") in tokens:
                return col
            # Score by how many entity tokens appear in the column name
            score = sum(1 for t in tokens if t in col_lower)
            # Penalise longer column names (prefer shorter, more direct IDs)
            score -= len(col_lower) * 0.01
            if score > best_score:
                best_score = score
                best_col = col
        return best_col

    @staticmethod
    def _ensure_unique_id(
        primary_id: str, id_columns: list[str], df: pd.DataFrame
    ) -> str | list[str]:
        """If the primary ID doesn't uniquely identify rows, find a composite key.

        Returns a single string if unique, or a list of strings for composite keys.
        """
        if len(df) == 0:
            return primary_id

        try:
            nunique = df[primary_id].nunique()
        except TypeError:
            return primary_id

        # If primary ID is unique enough (>= 90% of rows), use it as-is
        if nunique / len(df) >= 0.9:
            return primary_id

        # Look for a second column that, combined with primary, gives uniqueness
        # Prefer columns with "item", "line", or another ID suffix
        _ITEM_HINTS = ("item", "line", "schedule", "product", "storage")
        candidates = [
            col for col in df.columns
            if col != primary_id
            and any(h in col.lower() for h in _ITEM_HINTS)
        ]
        # Also add other id_columns as fallback
        candidates += [c for c in id_columns if c != primary_id and c not in candidates]

        for second_col in candidates:
            try:
                combined = df[[primary_id, second_col]].drop_duplicates()
                if len(combined) / len(df) >= 0.9:
                    return [primary_id, second_col]
            except (TypeError, KeyError):
                continue

        # Last resort: check all columns for a pair that's unique
        for col in df.columns:
            if col == primary_id:
                continue
            try:
                combined = df[[primary_id, col]].drop_duplicates()
                if len(combined) / len(df) >= 0.9:
                    return [primary_id, col]
            except TypeError:
                continue

        return primary_id

    # ------------------------------------------------------------------
    # Edge building — FK-only (replaces Jaccard-based _build_edges)
    # ------------------------------------------------------------------

    def _build_fk_edges(
        self,
        candidates: list[CandidateJoin],
        node_map: dict[str, NodeSchema],
        confidence_threshold: float,
    ) -> list[EdgeSchema]:
        """Filter candidates and convert to EdgeSchema list.

        Only accepts candidates where both entities are CORE_ENTITIES.
        """
        edges: list[EdgeSchema] = []
        seen: set[tuple[str, str, str, str]] = set()

        for c in candidates:
            # Skip low confidence
            if c.confidence < confidence_threshold:
                continue

            # Both entities must be core
            if c.source_entity not in CORE_ENTITIES or c.target_entity not in CORE_ENTITIES:
                continue

            # Skip generic / false-positive-prone fields
            if c.source_field in _GENERIC_FIELDS or c.target_field in _GENERIC_FIELDS:
                continue

            # Semantic filter: fields must share a common meaning
            if not self._fields_are_related(c.source_field, c.target_field):
                continue

            src_label = sanitize_label(c.source_entity)
            tgt_label = sanitize_label(c.target_entity)

            # Both entities must exist in node map
            if src_label not in node_map or tgt_label not in node_map:
                continue

            # Deduplicate
            key = (src_label, tgt_label, c.source_field, c.target_field)
            if key in seen:
                continue
            seen.add(key)

            edge_type = self._derive_edge_type(src_label, tgt_label, c.source_field)
            edges.append(EdgeSchema(
                type=edge_type,
                from_node=src_label,
                to_node=tgt_label,
                join_on=(c.source_field, c.target_field),
            ))

        return edges

    # ------------------------------------------------------------------
    # Bridge table edges — loaded from external config
    # ------------------------------------------------------------------

    def _load_bridge_edges(self, bridge_config_path: Path | None = None) -> list[EdgeSchema]:
        """Load bridge table edge definitions from a JSON config file."""
        path = bridge_config_path or _BRIDGE_CONFIG_PATH
        if not path.exists():
            logger.warning("Bridge config not found at %s — no bridge edges created", path)
            return []

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        edges: list[EdgeSchema] = []
        for bridge_entity, edge_defs in raw.items():
            for ed in edge_defs:
                try:
                    edge = EdgeSchema(
                        type=ed["type"],
                        from_node=ed["from_node"],
                        to_node=ed["to_node"],
                        join_on=tuple(ed["join_on"]),
                        source_entity=bridge_entity,
                        rel_properties=ed.get("rel_properties"),
                        bridge_target_field=ed.get("bridge_target_field"),
                    )
                    edges.append(edge)
                except Exception as e:
                    logger.error("Invalid bridge edge config for %s: %s", bridge_entity, e)

        logger.info("Loaded %d bridge edges from %s", len(edges), path)
        return edges

    # ------------------------------------------------------------------
    # Cardinality validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_cardinality(
        edge: EdgeSchema,
        dataframes: dict[str, pd.DataFrame],
    ) -> bool:
        """Warn if cardinality ratio is extreme (star anomaly risk)."""
        src_entity = edge.source_entity
        if not src_entity or src_entity not in dataframes:
            return True

        df = dataframes[src_entity]
        src_field = edge.join_on[0]
        bridge_tgt = edge.bridge_target_field or edge.join_on[1]

        if src_field not in df.columns or bridge_tgt not in df.columns:
            return True

        src_count = df[src_field].nunique()
        tgt_count = df[bridge_tgt].nunique()
        if min(src_count, tgt_count) == 0:
            return True

        ratio = max(src_count, tgt_count) / min(src_count, tgt_count)
        if ratio > 100:
            logger.warning(
                "High cardinality ratio for %s (%s→%s): %.0f:1 — star anomaly risk",
                edge.type, edge.from_node, edge.to_node, ratio,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fields_are_related(field_a: str, field_b: str) -> bool:
        """Check if two field names are semantically related."""
        if field_a == field_b:
            return True

        a_lower = field_a.lower()
        b_lower = field_b.lower()

        # One contains the other
        if a_lower in b_lower or b_lower in a_lower:
            return True

        # Extract camelCase tokens and check overlap
        tokens_a = set(t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", field_a))
        tokens_b = set(t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", field_b))

        # Require at least one meaningful shared token (excluding very short/common ones)
        shared = tokens_a & tokens_b
        meaningful = {t for t in shared if len(t) > 2}
        return len(meaningful) > 0

    @staticmethod
    def _derive_edge_type(from_label: str, to_label: str, join_field: str) -> str:
        """Generate a readable UPPER_SNAKE edge type."""
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", join_field).upper()
        return f"HAS_{snake}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_schema(
        self,
        dataframes: dict[str, pd.DataFrame],
        candidate_joins: list[CandidateJoin],
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> GraphSchema:
        """Build a full GraphSchema from dataframes + inferred joins.

        Only creates nodes for CORE_ENTITIES. Uses FK-based edges when
        USE_SCHEMA_INFERENCE is True, and always includes bridge table edges.
        """
        from app.ingestion.schema_inference import SchemaInference

        inference = SchemaInference(dataframes)

        # Build nodes — only for core entities
        node_map: dict[str, NodeSchema] = {}
        for entity_name, df in dataframes.items():
            if entity_name not in CORE_ENTITIES:
                continue
            id_cols = inference.detect_id_columns(df)
            node = self._build_node_schema(entity_name, df, id_cols)
            node_map[node.label] = node

        # Build edges
        edges: list[EdgeSchema] = []

        # FK-inferred edges (only when schema inference is enabled)
        if USE_SCHEMA_INFERENCE:
            fk_edges = self._build_fk_edges(candidate_joins, node_map, confidence_threshold)
            edges.extend(fk_edges)

        # Bridge table edges (always loaded from config)
        bridge_edges = self._load_bridge_edges()
        for be in bridge_edges:
            self._validate_cardinality(be, dataframes)
        edges.extend(bridge_edges)

        self._schema = GraphSchema(
            nodes=list(node_map.values()),
            edges=edges,
        )

        logger.info(
            "Built graph schema: %d node types, %d edge types (inference=%s)",
            len(self._schema.nodes), len(self._schema.edges), USE_SCHEMA_INFERENCE,
        )
        return self._schema

    def override_from_config(self, config: dict) -> GraphSchema:
        """Override or replace the current schema from a config dict.

        Config format:
        {
            "nodes": [ { "label": "...", "properties": {...}, "id_field": "..." } ],
            "edges": [ { "type": "...", "from_node": "...", "to_node": "...", "join_on": ["f1","f2"] } ]
        }
        """
        self._schema = GraphSchema.model_validate(config)
        logger.info(
            "Loaded schema override: %d nodes, %d edges",
            len(self._schema.nodes), len(self._schema.edges),
        )
        return self._schema

    def export_config(self, schema: GraphSchema, path: str) -> None:
        """Export the schema to a JSON file for inspection / manual editing."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(schema.model_dump(), f, indent=2)
        logger.info("Exported graph schema to %s", out_path)

    def load_config(self, path: str) -> GraphSchema:
        """Load a schema from a previously exported JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.override_from_config(data)
