from app.graph.graph_builder import BuildReport, GraphBuilder
from app.graph.neo4j_client import Neo4jClient
from app.ingestion.jsonl_loader import JsonlLoader
from app.ingestion.schema_inference import SchemaInference
from app.modeling.graph_schema import GraphSchema
from app.modeling.relationship_mapper import RelationshipMapper
from app.utils.logger import get_logger

logger = get_logger("services.graph_service")


class GraphService:
    def __init__(
        self,
        loader: JsonlLoader,
        inference: SchemaInference | None = None,
        mapper: RelationshipMapper | None = None,
        builder: GraphBuilder | None = None,
    ) -> None:
        self.loader = loader
        self.inference = inference
        self.mapper = mapper or RelationshipMapper()
        self.builder = builder
        self._schema: GraphSchema | None = None
        self._dataframes: dict | None = None

    def ingest(
        self,
        data_dir: str | None = None,
        config_override: dict | None = None,
        clear_existing: bool = False,
    ) -> BuildReport:
        """Full ingestion pipeline: load -> infer -> map -> build."""

        # 1. Load data
        logger.info("Step 1/4: Loading JSONL data")
        if data_dir:
            self.loader = JsonlLoader(data_dir)
        self._dataframes = self.loader.load_all()

        # 2. Infer schema
        logger.info("Step 2/4: Inferring schema")
        self.inference = SchemaInference(self._dataframes)
        candidate_joins = self.inference.infer_candidate_joins()

        # 3. Build graph schema (or override from config)
        logger.info("Step 3/4: Building graph schema")
        if config_override:
            self._schema = self.mapper.override_from_config(config_override)
        else:
            self._schema = self.mapper.build_schema(self._dataframes, candidate_joins)

        # 4. Build graph in Neo4j
        logger.info("Step 4/4: Building graph in Neo4j")
        if self.builder is None:
            raise RuntimeError("GraphBuilder not set — cannot build graph without Neo4j client")

        # Update builder with new schema
        self.builder.schema = self._schema

        if clear_existing:
            self.builder.clear_graph()

        report = self.builder.build_all(self._dataframes)

        logger.info(
            "Ingestion complete: %d node types, %d edge types, %d errors",
            len(report.nodes_created),
            len(report.edges_created),
            len(report.errors),
        )
        return report

    def get_schema(self) -> GraphSchema:
        if self._schema is None:
            raise RuntimeError("No schema available — run ingest() first")
        return self._schema

    def export_schema(self, path: str) -> None:
        self.mapper.export_config(self.get_schema(), path)

    @classmethod
    def create(
        cls,
        data_dir: str,
        neo4j_client: Neo4jClient,
    ) -> "GraphService":
        """Factory method to create a fully wired GraphService."""
        loader = JsonlLoader(data_dir)
        mapper = RelationshipMapper()
        # Builder is created with a placeholder schema; will be set during ingest()
        builder = GraphBuilder(neo4j_client, GraphSchema(nodes=[], edges=[]))
        return cls(loader=loader, mapper=mapper, builder=builder)
