import math

import pandas as pd
from pydantic import BaseModel

from app.config.constants import BATCH_SIZE
from app.graph.neo4j_client import Neo4jClient
from app.modeling.graph_schema import EdgeSchema, GraphSchema
from app.utils.logger import get_logger

logger = get_logger("graph.graph_builder")


class BuildReport(BaseModel):
    nodes_created: dict[str, int] = {}
    edges_created: dict[str, int] = {}
    errors: list[str] = []


class GraphBuilder:
    """Uses MERGE (not CREATE) for idempotent inserts. Uses id_field from NodeSchema as merge key."""

    def __init__(self, client: Neo4jClient, schema: GraphSchema) -> None:
        self.client = client
        self.schema = schema

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def merge_nodes(self, label: str, df: pd.DataFrame, id_fields: list[str]) -> int:
        """MERGE nodes for a single entity type in batches.

        Supports composite keys: id_fields can be ["salesOrder", "salesOrderItem"].
        """
        total = 0
        rows = self._df_to_records(df)
        batches = self._chunk(rows, BATCH_SIZE)

        # Build MERGE key clause: {field1: row.field1, field2: row.field2}
        merge_props = ", ".join(f"`{f}`: row.`{f}`" for f in id_fields)
        query = (
            f"UNWIND $rows AS row "
            f"MERGE (n:`{label}` {{{merge_props}}}) "
            f"SET n += row"
        )

        for i, batch in enumerate(batches):
            try:
                self.client.execute_write(query, {"rows": batch})
                total += len(batch)
            except Exception as e:
                logger.error("Failed merging nodes %s batch %d: %s", label, i, e)
                raise

        logger.info("Merged %d nodes for %s", total, label)
        return total

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def merge_edges(self, edge: EdgeSchema, dataframes: dict[str, pd.DataFrame]) -> int:
        """MERGE edges between two node types based on join fields.

        Supports two modes:
        1. Direct FK: reads from from_node's DataFrame (original behaviour).
        2. Bridge table: when ``edge.source_entity`` is set, reads from the
           bridge table DataFrame and uses ``edge.bridge_target_field`` for
           target matching and ``edge.rel_properties`` for relationship props.
        """
        src_field, tgt_field = edge.join_on

        # --- Determine which DataFrame supplies the join data ---------------
        if edge.source_entity and edge.source_entity in dataframes:
            join_df = dataframes[edge.source_entity]
        else:
            join_df = self._find_df_for_label(edge.from_node, dataframes)

        if join_df is None:
            logger.warning("Skipping edge %s: no DataFrame found", edge.type)
            return 0

        # Column in join_df that holds the target node's key value
        if edge.source_entity:
            # Bridge table: use bridge_target_field or fall back to tgt_field
            bridge_tgt_col = edge.bridge_target_field or tgt_field
        else:
            # Direct FK: the value comes from src_field in the from_node's DF
            bridge_tgt_col = src_field

        # Validate required columns exist
        if src_field not in join_df.columns:
            logger.warning(
                "Skipping edge %s: source field '%s' not in DataFrame (has %s)",
                edge.type, src_field, list(join_df.columns)[:10],
            )
            return 0
        if bridge_tgt_col not in join_df.columns:
            logger.warning(
                "Skipping edge %s: target field '%s' not in DataFrame",
                edge.type, bridge_tgt_col,
            )
            return 0

        src_node = self.schema.get_node(edge.from_node)
        tgt_node = self.schema.get_node(edge.to_node)
        if not src_node or not tgt_node:
            return 0

        # --- Collect needed columns -----------------------------------------
        src_id_fields = src_node.id_fields
        needed_cols = list(dict.fromkeys(src_id_fields + [src_field, bridge_tgt_col]))

        # Add relationship property columns
        rel_prop_cols: list[str] = []
        if edge.rel_properties:
            for prop in edge.rel_properties:
                if prop in join_df.columns and prop not in needed_cols:
                    needed_cols.append(prop)
                    rel_prop_cols.append(prop)

        missing = [c for c in needed_cols if c not in join_df.columns]
        if missing:
            logger.warning("Skipping edge %s: missing columns %s", edge.type, missing)
            return 0

        pairs = (
            join_df[needed_cols]
            .dropna(subset=[src_field, bridge_tgt_col])
            .drop_duplicates()
        )
        records = self._df_to_records(pairs)

        # --- Build Cypher ---------------------------------------------------
        src_match = ", ".join(f"`{f}`: row.`{f}`" for f in src_id_fields)
        query = (
            f"UNWIND $rows AS row "
            f"MATCH (a:`{edge.from_node}` {{{src_match}}}) "
            f"MATCH (b:`{edge.to_node}` {{`{tgt_field}`: row.`{bridge_tgt_col}`}}) "
            f"MERGE (a)-[r:`{edge.type}`]->(b)"
        )

        # SET relationship properties
        if rel_prop_cols:
            set_parts = [f"r.`{p}` = row.`{p}`" for p in rel_prop_cols]
            query += " SET " + ", ".join(set_parts)

        total = 0
        batches = self._chunk(records, BATCH_SIZE)
        for i, batch in enumerate(batches):
            try:
                self.client.execute_write(query, {"rows": batch})
                total += len(batch)
            except Exception as e:
                logger.error("Failed merging edges %s batch %d: %s", edge.type, i, e)
                raise

        logger.info(
            "Merged edges [%s] (%s)->(%s): %d pairs processed",
            edge.type, edge.from_node, edge.to_node, total,
        )
        return total

    # ------------------------------------------------------------------
    # Full build
    # ------------------------------------------------------------------

    def build_all(self, dataframes: dict[str, pd.DataFrame]) -> BuildReport:
        """Build the entire graph: nodes first, then edges."""
        report = BuildReport()

        # 1. Create indexes for merge performance
        self._create_indexes()

        # 2. Merge all nodes
        for node in self.schema.nodes:
            df = self._find_df_for_label(node.label, dataframes)
            if df is None:
                report.errors.append(f"No DataFrame found for node {node.label}")
                continue
            try:
                count = self.merge_nodes(node.label, df, node.id_fields)
                report.nodes_created[node.label] = count
            except Exception as e:
                report.errors.append(f"Node {node.label}: {e}")

        # 3. Merge all edges
        for edge in self.schema.edges:
            try:
                count = self.merge_edges(edge, dataframes)
                report.edges_created[edge.type] = report.edges_created.get(edge.type, 0) + count
            except Exception as e:
                report.errors.append(f"Edge {edge.type}: {e}")

        # 4. Post-build sanity checks
        self._run_sanity_checks(report)

        logger.info(
            "Build complete: %d node types, %d edge types, %d errors",
            len(report.nodes_created), len(report.edges_created), len(report.errors),
        )
        return report

    def clear_graph(self) -> None:
        """Delete all nodes and relationships."""
        self.client.execute_write("MATCH (n) DETACH DELETE n")
        logger.info("Graph cleared")

    # ------------------------------------------------------------------
    # Post-build sanity checks
    # ------------------------------------------------------------------

    def _run_sanity_checks(self, report: BuildReport) -> None:
        """Run post-build graph sanity checks and append warnings to report."""
        # 1. Check for duplicate nodes per label
        for node in self.schema.nodes:
            id_str = ", ".join(f"n.`{f}`" for f in node.id_fields)
            query = (
                f"MATCH (n:`{node.label}`) "
                f"WITH {id_str}, count(*) AS cnt "
                f"WHERE cnt > 1 "
                f"RETURN {id_str}, cnt ORDER BY cnt DESC LIMIT 5"
            )
            try:
                results = self.client.execute(query)
                if results:
                    report.errors.append(f"Duplicate nodes in {node.label}: {results}")
            except Exception as e:
                logger.debug("Sanity check skipped for %s: %s", node.label, e)

        # 2. Check for extreme high-degree nodes (star anomaly)
        try:
            query = (
                "MATCH (n) "
                "WITH n, size([(n)--() | 1]) AS degree "
                "WHERE degree > 200 "
                "RETURN labels(n)[0] AS label, count(n) AS cnt"
            )
            results = self.client.execute(query)
            if results:
                report.errors.append(f"Star anomaly detected: {results}")
        except Exception as e:
            logger.debug("Star anomaly check skipped: %s", e)

        # 3. Check for isolated nodes
        try:
            query = (
                "MATCH (n) WHERE NOT (n)--() "
                "RETURN labels(n)[0] AS label, count(n) AS cnt"
            )
            results = self.client.execute(query)
            for r in results:
                logger.warning("Isolated nodes: %s = %s", r.get("label"), r.get("cnt"))
        except Exception as e:
            logger.debug("Isolation check skipped: %s", e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_indexes(self) -> None:
        """Create indexes on id_field(s) for each node label to speed up MERGE."""
        for node in self.schema.nodes:
            fields = node.id_fields
            index_name = f"idx_{node.label}_{'_'.join(fields)}"
            props = ", ".join(f"n.`{f}`" for f in fields)
            query = (
                f"CREATE INDEX {index_name} IF NOT EXISTS "
                f"FOR (n:`{node.label}`) ON ({props})"
            )
            try:
                self.client.execute_write(query)
            except Exception as e:
                logger.debug("Index creation note for %s: %s", node.label, e)

    def _find_df_for_label(self, label: str, dataframes: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
        """Find the DataFrame matching a node label, using source_entity when available."""
        # Check source_entity from schema first (supports label != folder name)
        for node in self.schema.nodes:
            if node.label == label and node.source_entity and node.source_entity in dataframes:
                return dataframes[node.source_entity]
        # Fallback: original sanitize_label matching
        for entity_name, df in dataframes.items():
            from app.utils.helpers import sanitize_label
            if sanitize_label(entity_name) == label:
                return df
        return None

    @staticmethod
    def _df_to_records(df: pd.DataFrame) -> list[dict]:
        """Convert DataFrame to list of dicts, stringifying values and dropping nested objects."""
        records = []
        for row in df.to_dict("records"):
            clean = {}
            for k, v in row.items():
                if isinstance(v, dict):
                    continue  # skip nested objects (e.g. creationTime)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue  # skip nulls
                clean[k] = str(v)
            records.append(clean)
        return records

    @staticmethod
    def _chunk(items: list, size: int) -> list[list]:
        return [items[i : i + size] for i in range(0, len(items), size)]
