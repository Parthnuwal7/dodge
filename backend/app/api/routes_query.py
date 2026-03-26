from fastapi import APIRouter, HTTPException, Query
from functools import lru_cache
from pydantic import BaseModel

from app.config.constants import API_PREFIX
from app.config.settings import get_settings
from app.graph.neo4j_client import Neo4jClient
from app.modeling.graph_schema import GraphSchema
from app.query.query_router import QueryRoutingError
from app.services.chat_logger import SupabaseChatLogger
from app.services.query_service import QueryService
from app.utils.logger import get_logger

logger = get_logger("api.routes_query")
router = APIRouter(prefix=f"{API_PREFIX}/query", tags=["query"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    schema_json: dict | None = None
    session_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    explanation: str
    query_used: str
    nodes: list[dict]
    edges: list[dict]
    data: list[dict]
    metadata: dict


class ChatLoggerStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    table: str
    message: str


class ChatHistoryItem(BaseModel):
    created_at: str
    session_id: str | None = None
    question: str
    answer: str
    explanation: str
    query_used: str
    metadata: dict
    node_count: int
    edge_count: int
    record_count: int
    status: str
    error: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    items: list[ChatHistoryItem]


class ChatClearResponse(BaseModel):
    session_id: str
    deleted_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_query_service(schema: GraphSchema) -> tuple[QueryService, Neo4jClient]:
    """Wire up QueryService from settings. Returns (service, client) so caller can close client."""
    settings = get_settings()
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    service = QueryService.create(settings, client, schema)
    return service, client


@lru_cache(maxsize=1)
def _get_chat_logger() -> SupabaseChatLogger:
    return SupabaseChatLogger(get_settings())


def _load_schema(schema_json: dict | None) -> GraphSchema:
    """Load schema from request body or from the saved config file."""
    if schema_json:
        return GraphSchema.model_validate(schema_json)

    # Try loading from saved config files
    import json
    from pathlib import Path
    for filename in ("graph_schema_curated.json", "graph_schema.json"):
        path = Path(filename)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return GraphSchema.model_validate(json.load(f))

    raise HTTPException(
        status_code=400,
        detail="No schema provided and no schema file found. "
               "Run /graph/preview + /graph/build first, or pass schema_json in the request.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    """Natural language query endpoint.

    Accepts a question, routes it through the full pipeline
    (guardrails -> intent extraction -> template -> Cypher -> execution -> formatting),
    and returns a structured response.
    """
    schema = _load_schema(request.schema_json)
    service, client = _build_query_service(schema)
    chat_logger = _get_chat_logger()

    try:
        response = service.ask(request.question)
        response_metadata = dict(response.metadata)
        if request.session_id:
            response_metadata["session_id"] = request.session_id

        chat_logger.log(
            session_id=request.session_id,
            question=request.question,
            answer=response.answer,
            explanation=response.explanation,
            query_used=response.query_used,
            metadata=response_metadata,
            node_count=len(response.nodes),
            edge_count=len(response.edges),
            record_count=len(response.data),
            status="success",
        )
        return AskResponse(
            answer=response.answer,
            explanation=response.explanation,
            query_used=response.query_used,
            nodes=[n.model_dump() for n in response.nodes],
            edges=[e.model_dump() for e in response.edges],
            data=response.data,
            metadata=response_metadata,
        )
    except QueryRoutingError as e:
        logger.warning("Query routing failed at stage '%s': %s", e.stage, e)
        chat_logger.log(
            session_id=request.session_id,
            question=request.question,
            answer="",
            explanation="",
            query_used="",
            metadata={"stage": e.stage},
            node_count=0,
            edge_count=0,
            record_count=0,
            status="routing_error",
            error=str(e),
        )
        raise HTTPException(status_code=422, detail={
            "message": str(e),
            "stage": e.stage,
        })
    except Exception as e:
        logger.error("Query failed: %s", e)
        chat_logger.log(
            session_id=request.session_id,
            question=request.question,
            answer="",
            explanation="",
            query_used="",
            metadata={},
            node_count=0,
            edge_count=0,
            record_count=0,
            status="error",
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        client.close()


@router.get("/chat/status", response_model=ChatLoggerStatusResponse)
def chat_status():
    logger_state = _get_chat_logger().health()
    return ChatLoggerStatusResponse(**logger_state)


@router.get("/chat/history", response_model=ChatHistoryResponse)
def chat_history(session_id: str = Query(...), limit: int = Query(200, ge=1, le=500)):
    items = _get_chat_logger().list_session(session_id=session_id, limit=limit)
    return ChatHistoryResponse(session_id=session_id, items=[ChatHistoryItem(**item) for item in items])


@router.delete("/chat/history", response_model=ChatClearResponse)
def clear_chat_history(session_id: str = Query(...)):
    deleted_count = _get_chat_logger().clear_session(session_id=session_id)
    return ChatClearResponse(session_id=session_id, deleted_count=deleted_count)
