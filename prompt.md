## System Architecture:

        Data Layer (JSONL)
            ↓
        Schema & Relationship Inference Layer
            ↓
        Relationship Mapping (Config + Optional UI)
            ↓
        Graph Construction Engine
            ↓
        Neo4j (Graph DB)
        -----------------------------------------
        Query Pipeline:
        User Query
            ↓
        Guardrail Filter
            ↓
        Intent + Entity Extraction (LLM)
            ↓
        Query Template Selection
            ↓
        Cypher Generation (Controlled)
            ↓
        Query Validator
            ↓
        Execution (Neo4j)
            ↓
        Result Formatter + Path Extractor
        -----------------------------------------
            ↓
        UI Layer:
            - Graph Visualization (Cytoscape)
            - Chat Interface
            - Highlighted Paths

## Backend structure:
        backend/
        │
        ├── app/
        │   ├── main.py
        │   ├── config/
        │   │   ├── settings.py
        │   │   └── constants.py
        │   │
        │   ├── ingestion/
        │   │   ├── jsonl_loader.py
        │   │   └── schema_inference.py
        │   │
        │   ├── modeling/
        │   │   ├── relationship_mapper.py
        │   │   └── graph_schema.py
        │   │
        │   ├── graph/
        │   │   ├── neo4j_client.py
        │   │   └── graph_builder.py
        │   │
        │   ├── llm/
        │   │   ├── prompt_manager.py
        │   │   ├── intent_extractor.py
        │   │   ├── cypher_generator.py
        │   │   └── guardrails.py
        │   │
        │   ├── query/
        │   │   ├── query_router.py
        │   │   ├── query_validator.py
        │   │   └── execution_engine.py
        │   │
        │   ├── services/
        │   │   ├── graph_service.py
        │   │   └── query_service.py
        │   │
        │   ├── api/
        │   │   ├── routes_graph.py
        │   │   └── routes_query.py
        │   │
        │   └── utils/
        │       ├── logger.py
        │       └── helpers.py

## Core Design Principles:

- Follow clean OOP design
- Each module has single responsibility
- No business logic in API routes
- Strong typing (pydantic models)
- No hardcoded values inside logic
- All queries must be deterministic and explainable
- LLM is used ONLY for translation, not reasoning

## Key Components:

### 4.1 JSONL Loader
- Read all folders
- Normalize into DataFrames
- Provide schema summary

### 4.2 Schema Inference
- Detect:
    - ID columns
    - overlapping values
    - candidate joins

### 4.3 Relationship Manager
- Store relationships in config
- Allow override

### 4.4 Graph Builder
- Convert rows → nodes + edges
- Batch insert into Neo4j

### 4.5 LLM Layer (VERY CONTROLLED)
Split into:
1. Intent Extractor
2. Query Template Selector
3. Cypher Generator (param filling ONLY)

### 4.6 Query Validator

Reject:
- unknown nodes
- invalid relationships
- unsafe queries

### 4.7 Execution Engine
- Run Cypher
- Return:
    - data
    - nodes
    - relationships

### 4.8 Response Formatter
Convert to:
````json
{
  "answer": "...",
  "nodes": [],
  "edges": [],
  "metadata": {}
}
````