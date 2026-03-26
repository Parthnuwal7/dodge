from app.config.settings import Settings
from app.graph.neo4j_client import Neo4jClient
from app.llm.cypher_generator import CypherGenerator
from app.llm.guardrails import Guardrails
from app.llm.intent_extractor import IntentExtractor
from app.llm.llm_client import FallbackLLMClient
from app.llm.prompt_manager import PromptManager
from app.llm.template_registry import QueryTemplateRegistry
from app.modeling.graph_schema import GraphSchema
from app.query.execution_engine import ExecutionEngine
from app.query.path_extractor import PathExtractor
from app.query.query_router import QueryRouter, QueryRoutingError
from app.query.query_validator import QueryValidator
from app.query.response_formatter import QueryResponse, ResponseFormatter
from app.utils.logger import get_logger

logger = get_logger("services.query_service")


class QueryService:
    def __init__(
        self,
        router: QueryRouter,
        engine: ExecutionEngine,
        formatter: ResponseFormatter,
    ) -> None:
        self.router = router
        self.engine = engine
        self.formatter = formatter

    def ask(self, user_query: str) -> QueryResponse:
        """Full query pipeline: route -> execute -> format."""
        # 1. Route (intent extraction, template selection, Cypher generation, validation)
        routed = self.router.route(user_query)
        logger.info(
            "Routed query: template=%s, cypher=%s",
            routed.template_name, routed.cypher,
        )

        # 2. Execute
        result = self.engine.execute(routed.cypher)

        # 3. Format
        response = self.formatter.format(routed, result)
        logger.info(
            "Response: %d nodes, %d edges, %.1fms",
            len(response.nodes), len(response.edges), result.execution_time_ms,
        )

        return response

    @classmethod
    def create(cls, settings: Settings, neo4j_client: Neo4jClient, schema: GraphSchema) -> "QueryService":
        """Factory method to wire up all query pipeline components."""
        # LLM client with Groq fallback
        llm_client = FallbackLLMClient.from_settings(settings)

        # Components
        prompt_manager = PromptManager()
        guardrails = Guardrails(
            blocked_patterns=["ignore previous", "forget your instructions", "system prompt"],
            allowed_domains=schema.node_labels(),
        )
        intent_extractor = IntentExtractor(prompt_manager, llm_client, settings.llm_model)
        template_registry = QueryTemplateRegistry(settings.cypher_template_dir)
        cypher_generator = CypherGenerator()
        validator = QueryValidator(schema)

        router = QueryRouter(
            guardrails=guardrails,
            intent_extractor=intent_extractor,
            template_registry=template_registry,
            cypher_generator=cypher_generator,
            validator=validator,
            schema=schema,
            llm_client=llm_client,
            llm_model=settings.llm_model,
            prompt_manager=prompt_manager,
        )

        path_extractor = PathExtractor()
        engine = ExecutionEngine(neo4j_client, path_extractor)
        formatter = ResponseFormatter(
            llm_client=llm_client,
            model=settings.llm_model,
            prompt_manager=prompt_manager,
        )

        return cls(router=router, engine=engine, formatter=formatter)
