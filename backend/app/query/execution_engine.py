import time

from pydantic import BaseModel

from app.graph.neo4j_client import Neo4jClient
from app.query.path_extractor import GraphPath, PathExtractor
from app.utils.logger import get_logger

logger = get_logger("query.execution_engine")


class QueryResult(BaseModel):
    data: list[dict]
    graph: GraphPath
    execution_time_ms: float = 0.0


class ExecutionEngine:
    def __init__(self, client: Neo4jClient, path_extractor: PathExtractor) -> None:
        self.client = client
        self.path_extractor = path_extractor

    def execute(self, cypher: str) -> QueryResult:
        """Execute a Cypher query and return structured results."""
        start = time.time()

        try:
            raw_records = self.client.execute(cypher)
        except Exception as e:
            logger.error("Cypher execution failed: %s", e)
            raise

        elapsed_ms = (time.time() - start) * 1000

        logger.info("Query returned %d records in %.1fms", len(raw_records), elapsed_ms)

        # Extract graph structure for visualization
        graph = self.path_extractor.extract(raw_records)

        return QueryResult(
            data=raw_records,
            graph=graph,
            execution_time_ms=round(elapsed_ms, 2),
        )
