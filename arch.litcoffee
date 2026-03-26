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