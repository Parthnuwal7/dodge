from neo4j import GraphDatabase

from app.config.constants import NEO4J_CONNECTION_TIMEOUT, NEO4J_MAX_CONNECTION_POOL_SIZE
from app.utils.logger import get_logger

logger = get_logger("graph.neo4j_client")


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=NEO4J_MAX_CONNECTION_POOL_SIZE,
            connection_timeout=NEO4J_CONNECTION_TIMEOUT,
        )
        logger.info("Neo4j driver created for %s", uri)

    def verify_connectivity(self) -> bool:
        try:
            self._driver.verify_connectivity()
            logger.info("Neo4j connectivity verified")
            return True
        except Exception as e:
            logger.error("Neo4j connectivity check failed: %s", e)
            return False

    def execute(self, query: str, params: dict | None = None) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]

    def execute_write(self, query: str, params: dict | None = None) -> list[dict]:
        with self._driver.session() as session:
            result = session.execute_write(
                lambda tx: list(tx.run(query, params or {}))
            )
            return [record.data() for record in result]

    def batch_execute(self, queries: list[tuple[str, dict]]) -> None:
        with self._driver.session() as session:
            def _run_batch(tx):
                for query, params in queries:
                    tx.run(query, params)
            session.execute_write(_run_batch)

    def close(self) -> None:
        self._driver.close()
        logger.info("Neo4j driver closed")
