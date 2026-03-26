# Implementation Plan

## Step 1: System Understanding

### 1.1 System Architecture

Two main pipelines:

**Data Pipeline:** JSONL files -> Schema inference -> Relationship mapping -> Graph construction -> Neo4j

**Query Pipeline:** User query -> Guardrail filter -> Intent/entity extraction (LLM) -> Template selection -> Controlled Cypher generation -> Validation -> Execution -> Formatted response

**UI Layer:** Cytoscape graph visualization, chat interface, highlighted paths.

### 1.2 Backend Folder Structure

```
backend/
├── app/
│   ├── main.py                        # FastAPI entrypoint
│   ├── config/
│   │   ├── settings.py                # Env-based config (BaseSettings)
│   │   └── constants.py               # App-wide constants
│   ├── ingestion/
│   │   ├── jsonl_loader.py            # JSONL reading + DataFrame normalization
│   │   └── schema_inference.py        # ID detection, candidate joins (+ CandidateJoin model)
│   ├── modeling/
│   │   ├── relationship_mapper.py     # Config-driven relationship management
│   │   └── graph_schema.py            # NodeSchema, EdgeSchema, GraphSchema models
│   ├── graph/
│   │   ├── neo4j_client.py            # Neo4j connection + query execution
│   │   └── graph_builder.py           # MERGE-based node/edge creation, batch insert (+ BuildReport model)
│   ├── llm/
│   │   ├── prompt_manager.py          # Prompt template loading + rendering
│   │   ├── intent_extractor.py        # Intent + entity extraction (+ QueryIntent model)
│   │   ├── cypher_generator.py        # Template param filling ONLY (+ QueryTemplate model)
│   │   ├── template_registry.py       # Load + select .cypher templates (+ QueryTemplateRegistry)
│   │   └── guardrails.py              # Input/output/domain validation (+ GuardrailResult model)
│   ├── query/
│   │   ├── query_router.py            # Pipeline orchestration (+ RoutedQuery model)
│   │   ├── query_validator.py         # Schema-aware Cypher validation (+ ValidationResult model)
│   │   ├── execution_engine.py        # Cypher execution + graph extraction (+ QueryResult model)
│   │   ├── path_extractor.py          # Extract nodes/edges from raw Neo4j results (+ GraphPath model)
│   │   └── response_formatter.py      # Build final QueryResponse (+ QueryResponse model)
│   ├── services/
│   │   ├── graph_service.py           # Ingestion orchestration
│   │   └── query_service.py           # Query orchestration
│   ├── api/
│   │   ├── routes_graph.py            # Graph/ingestion endpoints
│   │   └── routes_query.py            # Query endpoints
│   └── utils/
│       ├── logger.py                  # Structured logging setup
│       └── helpers.py                 # Shared utilities
├── templates/
│   └── cypher/                        # External .cypher template files
│       ├── find_node.cypher
│       ├── find_path.cypher
│       ├── list_neighbors.cypher
│       └── aggregate.cypher
```

Pydantic models live in their owning modules (no separate `models/` package). Each model is defined alongside the logic that produces or consumes it.

### 1.3 Core Design Principles

| Principle | Implication |
|---|---|
| Clean OOP | Classes with single responsibility |
| No logic in routes | Routes delegate to services |
| Strong typing | Pydantic models everywhere |
| No hardcoded values | Config/constants only |
| Deterministic queries | Explainable, reproducible results |
| LLM = translation only | No reasoning, no decision-making |

### 1.4 Key Components & Responsibilities

| Component | Responsibility |
|---|---|
| JSONL Loader | Read folders, normalize to DataFrames, provide schema summary |
| Schema Inference | Detect ID columns, overlapping values, candidate joins |
| Relationship Manager | Store relationships in config, allow override |
| Graph Builder | MERGE-based node/edge creation using id_field, batch insert into Neo4j |
| Intent Extractor | Extract user intent + entities from natural language |
| Query Template Registry | Load .cypher files, select template by intent type |
| Cypher Generator | Fill parameters into selected template -- nothing more |
| Guardrails | Input sanitization, output validation, domain-aware rejection |
| Query Router | Orchestrate pipeline, return RoutedQuery (cypher + intent + template + params) |
| Query Validator | Reject unknown nodes, invalid relationships, unsafe queries |
| Execution Engine | Run Cypher, delegate to PathExtractor for graph data |
| Path Extractor | Extract nodes + relationships from raw Neo4j results for highlighting |
| Response Formatter | Build final response: answer, explanation, nodes, edges, metadata |

---

## Step 2: Architecture Validation

### Strengths
- Clean separation of concerns across all layers
- LLM is correctly sandboxed -- no open-ended generation
- Validator before execution is a solid safety net
- Service layer prevents route bloat

### Risks & Gaps

| Issue | Severity | Recommendation |
|---|---|---|
| **No error handling strategy** | Medium | Need consistent exception handling via FastAPI exception handlers in `main.py`. |
| **Schema inference can be fragile** | Medium | Overlapping values != valid joins. The relationship manager config override is the right escape hatch -- just ensure it's the primary source of truth, with inference as a suggestion layer only. |
| **No auth or rate limiting mentioned** | Low | Fine for MVP, but worth noting for production. |
| **No data validation on JSONL input** | Medium | Malformed JSONL will propagate silently. Loader should validate and report skipped/invalid records. |

**Note:** Pydantic models are co-located within their owning modules per prompt.md structure. No separate `models/` or `core/` packages.

---

## Step 3: Execution Plan

### Phase 1: Project Scaffolding
**Modules:** `main.py`, `config/settings.py`, `config/constants.py`, `utils/logger.py`, `utils/helpers.py`
**Responsibilities:** FastAPI app init, env-based config via Pydantic `BaseSettings`, logging setup, folder structure creation
**Output:** Runnable empty FastAPI app with health check, config loading, structured logging

### Phase 2: Data Ingestion + Schema Inference
**Modules:** `ingestion/jsonl_loader.py`, `ingestion/schema_inference.py`
**Responsibilities:** Recursive JSONL reading, DataFrame normalization, column type detection, ID column detection, candidate join discovery
**Output:** Loaded DataFrames + schema summary dict per entity type + list of candidate joins

### Phase 3: Relationship Mapping
**Modules:** `modeling/relationship_mapper.py`, `modeling/graph_schema.py`
**Responsibilities:** Persist relationships in config, allow manual override, define node labels + edge types from schema
**Output:** Graph schema config (node types, properties, edge definitions) -- serializable and inspectable

### Phase 4: Graph Construction
**Modules:** `graph/neo4j_client.py`, `graph/graph_builder.py`, `services/graph_service.py`
**Responsibilities:** Neo4j connection management, batch node/edge creation, full pipeline orchestration (load -> infer -> map -> build)
**Output:** Populated Neo4j database, ingestion summary/report

### Phase 5: LLM Query Pipeline
**Modules:** `llm/prompt_manager.py`, `llm/intent_extractor.py`, `llm/cypher_generator.py`, `llm/template_registry.py`, `llm/guardrails.py`
**Responsibilities:** Prompt template management, intent + entity extraction, .cypher template loading + selection, parameter filling, input/output/domain guardrails with explicit rejection
**Output:** Structured intent object -> selected template -> parameterized Cypher string

### Phase 6: Query Validation + Execution
**Modules:** `query/query_router.py`, `query/query_validator.py`, `query/execution_engine.py`, `query/path_extractor.py`, `query/response_formatter.py`, `services/query_service.py`
**Responsibilities:** Route query through pipeline (returns RoutedQuery), validate Cypher against known schema, execute query, extract graph paths for highlighting, format final response with answer + explanation + nodes + edges + metadata
**Output:** RoutedQuery -> validated Cypher -> execution -> structured QueryResponse

### Phase 7: API Layer
**Modules:** `api/routes_graph.py`, `api/routes_query.py`
**Responsibilities:** HTTP endpoints for ingestion triggers, graph status, natural language queries, direct Cypher (if allowed)
**Output:** Complete REST API

**Important: Schema review before graph build**
The ingestion flow must support a two-step process:
1. `POST /ingest/preview` — loads data + infers schema, returns proposed GraphSchema (nodes with id_fields, edges) for user review. No data is written to Neo4j.
2. `POST /ingest/build` — accepts a (possibly user-edited) GraphSchema and builds the graph in Neo4j.

This prevents data loss from erroneous auto-detected primary keys or false-positive joins. The UI should present the inferred schema for confirmation/editing before any graph construction happens.

---

## Step 4: Interface Definitions

### config/settings.py
```python
class Settings(BaseSettings):
    # Neo4j Aura
    neo4j_uri: str                # neo4j+s://<aura-instance>.databases.neo4j.io
    neo4j_user: str
    neo4j_password: str

    # LLM via OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str                # e.g., "meta-llama/llama-3-70b-instruct" (TBD)

    # Data
    data_dir: str
    cypher_template_dir: str = "templates/cypher"

    # General
    log_level: str = "INFO"
```

### ingestion/jsonl_loader.py
```python
class JsonlLoader:
    def __init__(self, data_dir: str) -> None: ...
    def load_all(self) -> dict[str, pd.DataFrame]: ...
    def load_file(self, file_path: str) -> pd.DataFrame: ...
    def get_schema_summary(self) -> dict[str, dict]: ...
```

### ingestion/schema_inference.py
```python
class CandidateJoin(BaseModel):
    source_entity: str
    target_entity: str
    source_field: str
    target_field: str
    confidence: float

class SchemaInference:
    def __init__(self, dataframes: dict[str, pd.DataFrame]) -> None: ...
    def detect_id_columns(self, df: pd.DataFrame) -> list[str]: ...
    def detect_overlapping_values(self) -> list[CandidateJoin]: ...
    def infer_candidate_joins(self) -> list[CandidateJoin]: ...
```

### modeling/graph_schema.py
```python
class NodeSchema(BaseModel):
    label: str
    properties: dict[str, str]        # name -> type
    id_field: str

class EdgeSchema(BaseModel):
    type: str
    from_node: str
    to_node: str
    join_on: tuple[str, str]           # (source_field, target_field)

class GraphSchema(BaseModel):
    nodes: list[NodeSchema]
    edges: list[EdgeSchema]
```

### modeling/relationship_mapper.py
```python
class RelationshipMapper:
    def __init__(self, config_path: str | None = None) -> None: ...
    def build_schema(
        self,
        dataframes: dict[str, pd.DataFrame],
        candidate_joins: list[CandidateJoin],
    ) -> GraphSchema: ...
    def override_from_config(self, config: dict) -> GraphSchema: ...
    def export_config(self, schema: GraphSchema, path: str) -> None: ...
```

### graph/neo4j_client.py
```python
class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None: ...
    def execute(self, query: str, params: dict | None = None) -> list[dict]: ...
    def batch_execute(self, queries: list[tuple[str, dict]]) -> None: ...
    def close(self) -> None: ...
```

### graph/graph_builder.py
```python
class BuildReport(BaseModel):
    nodes_created: dict[str, int]
    edges_created: dict[str, int]
    errors: list[str]

class GraphBuilder:
    """Uses MERGE (not CREATE) for idempotent inserts. Uses id_field from NodeSchema as merge key."""
    def __init__(self, client: Neo4jClient, schema: GraphSchema) -> None: ...
    def merge_nodes(self, label: str, df: pd.DataFrame, id_field: str) -> int: ...
    def merge_edges(self, edge: EdgeSchema, dataframes: dict[str, pd.DataFrame]) -> int: ...
    def build_all(self, dataframes: dict[str, pd.DataFrame]) -> BuildReport: ...
    def clear_graph(self) -> None: ...
```

### llm/guardrails.py
```python
class GuardrailResult(BaseModel):
    passed: bool
    reason: str | None = None
    rejection_type: str | None = None  # "blocked_pattern", "off_domain", "unsafe_cypher"

class Guardrails:
    def __init__(
        self,
        blocked_patterns: list[str] | None = None,
        allowed_domains: list[str] | None = None,   # valid node labels / entity types
    ) -> None: ...
    def validate_input(self, user_query: str) -> GuardrailResult: ...
    def validate_domain(self, intent: QueryIntent, schema: GraphSchema) -> GuardrailResult: ...
    def validate_output(self, cypher: str) -> GuardrailResult: ...
```

### llm/intent_extractor.py
```python
class QueryIntent(BaseModel):
    intent_type: str          # e.g., "find_path", "list_nodes", "aggregate"
    entities: list[str]
    filters: dict[str, Any]
    raw_query: str
    confidence: float

class IntentExtractor:
    def __init__(self, prompt_manager: PromptManager, llm_client: Any) -> None: ...
    def extract(self, user_query: str, schema: GraphSchema) -> QueryIntent: ...
```

### llm/template_registry.py
```python
class QueryTemplate(BaseModel):
    name: str
    cypher: str
    required_params: list[str]
    description: str              # used for intent-to-template matching

class QueryTemplateRegistry:
    """Loads .cypher files from templates/cypher/ directory."""
    def __init__(self, template_dir: str) -> None: ...
    def load_templates(self) -> None: ...
    def get_template(self, name: str) -> QueryTemplate: ...
    def select_template(self, intent: QueryIntent) -> QueryTemplate: ...
    def list_templates(self) -> list[str]: ...
```

### llm/cypher_generator.py
```python
class CypherGenerator:
    """Pure parameter filling. No LLM reasoning."""
    def generate(
        self,
        template: QueryTemplate,
        parameters: dict,
    ) -> str: ...
```

### llm/prompt_manager.py
```python
class PromptManager:
    def __init__(self, template_dir: str | None = None) -> None: ...
    def get_template(self, name: str) -> str: ...
    def render(self, name: str, context: dict) -> str: ...
```

### query/query_router.py
```python
class RoutedQuery(BaseModel):
    cypher: str
    intent: QueryIntent
    template_name: str
    parameters: dict

class QueryRouter:
    def __init__(
        self,
        guardrails: Guardrails,
        intent_extractor: IntentExtractor,
        template_registry: QueryTemplateRegistry,
        cypher_generator: CypherGenerator,
        validator: QueryValidator,
    ) -> None: ...
    def route(self, user_query: str) -> RoutedQuery: ...
```

### query/query_validator.py
```python
class ValidationResult(BaseModel):
    valid: bool
    errors: list[str]

class QueryValidator:
    def __init__(self, schema: GraphSchema) -> None: ...
    def validate(self, cypher: str) -> ValidationResult: ...
```

### query/path_extractor.py
```python
class GraphNode(BaseModel):
    id: str
    label: str
    properties: dict

class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: dict

class GraphPath(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]

class PathExtractor:
    """Extracts structured node/edge data from raw Neo4j result records for graph highlighting."""
    def extract(self, raw_records: list[dict]) -> GraphPath: ...
```

### query/execution_engine.py
```python
class QueryResult(BaseModel):
    data: list[dict]
    graph: GraphPath              # structured nodes + edges for visualization

class ExecutionEngine:
    def __init__(self, client: Neo4jClient, path_extractor: PathExtractor) -> None: ...
    def execute(self, cypher: str) -> QueryResult: ...
```

### query/response_formatter.py
```python
class QueryResponse(BaseModel):
    answer: str
    explanation: str              # human-readable query explanation
    query_used: str               # the Cypher that was executed
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: dict                # template_name, intent_type, execution_time, etc.

class ResponseFormatter:
    """Builds the final response from RoutedQuery + QueryResult."""
    def format(self, routed_query: RoutedQuery, result: QueryResult) -> QueryResponse: ...
```

### services/graph_service.py
```python
class GraphService:
    def __init__(self, loader: JsonlLoader, inference: SchemaInference,
                 mapper: RelationshipMapper, builder: GraphBuilder) -> None: ...
    def ingest(self, data_dir: str, config_override: dict | None = None) -> BuildReport: ...
    def get_schema(self) -> GraphSchema: ...
```

### services/query_service.py
```python
class QueryService:
    def __init__(self, router: QueryRouter, engine: ExecutionEngine,
                 formatter: ResponseFormatter) -> None: ...
    def ask(self, user_query: str) -> QueryResponse: ...
```

### Model Location Summary

| Model | Defined In |
|---|---|
| `CandidateJoin` | `ingestion/schema_inference.py` |
| `NodeSchema`, `EdgeSchema`, `GraphSchema` | `modeling/graph_schema.py` |
| `BuildReport` | `graph/graph_builder.py` |
| `GuardrailResult` | `llm/guardrails.py` |
| `QueryIntent` | `llm/intent_extractor.py` |
| `QueryTemplate`, `QueryTemplateRegistry` | `llm/template_registry.py` |
| `RoutedQuery` | `query/query_router.py` |
| `ValidationResult` | `query/query_validator.py` |
| `GraphNode`, `GraphEdge`, `GraphPath` | `query/path_extractor.py` |
| `QueryResult` | `query/execution_engine.py` |
| `QueryResponse`, `ResponseFormatter` | `query/response_formatter.py` |

---

## Resolved Decisions

1. **JSONL structure** -- **Flat.** One entity type per folder, flat key-value JSON records, multiple partition files per folder. 21 entity types (SAP Order-to-Cash dataset). `JsonlLoader` reads all `.jsonl` files per subfolder and concatenates into one DataFrame per entity.

2. **Neo4j deployment** -- **Aura cloud.** `neo4j_client.py` will use `neo4j+s://` URI scheme. Connection settings via `Settings` (env-based).

3. **LLM provider** -- **OpenRouter.** Model TBD (will be specified later). `prompt_manager.py` and `intent_extractor.py` will use OpenRouter-compatible API (OpenAI-compatible endpoint). Model name configured via `Settings.llm_model`.
