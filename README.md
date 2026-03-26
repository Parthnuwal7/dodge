---
title: Dodge
emoji: "🚀"
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Dodge Graph Query Assistant

Live Demo link: 
Backend link: 
Video link: https://youtu.be/7pkjkYFTdA0

## What This Project Does
This project turns Order-to-Cash business data into a graph and lets users ask natural-language questions over that graph.

- Backend: FastAPI + Neo4j + LLM routing
- Frontend: React + Vite + Cytoscape visualization
- Optional chat persistence: Supabase

## Solution Approach
We built the system in two connected flows:

1. Data flow (model the business process as a graph)
2. Query flow (translate user questions into safe Cypher and return both table + path data)

The design goal is to keep queries explainable, safe, and debuggable while still supporting flexible natural language.

## Architecture Decisions

### 1) Database Choice: Neo4j
Neo4j was chosen because Order-to-Cash is inherently relationship-heavy (Customer -> SalesOrder -> Delivery -> Invoice -> Payment).

Why Neo4j here:
- Multi-hop process traversal is first-class
- Relationship semantics are explicit and queryable
- Path exploration and graph visualization map naturally to the domain

### 2) API Layer: FastAPI
FastAPI provides typed request/response contracts, clear route separation, and fast iteration.

Key backend route groups:
- Graph routes: schema preview/build/explore/status/neighbors
- Query routes: ask question, chat status/history clear

### 3) Frontend Stack: React + Cytoscape
The UI was designed around two views:
- Full graph exploration
- Query-result path view focused on relevant nodes/edges

Cytoscape is used for interactive graph rendering and path highlighting.

### 4) Chat Persistence: Supabase
Supabase stores session-based query/response history so users can reload and continue context until they press Quit.

## Data Processing Pipeline

### Ingestion/Modeling
1. Read SAP O2C source files
2. Infer/curate graph schema (labels, relationships, keys)
3. Build nodes and relationships in Neo4j
4. Expose graph status and explore endpoints

### Graph Schema as Control Plane
The schema is not only for ingestion; it also controls query generation and validation.

## Query Processing Pipeline
For `/api/v1/query/ask`, the backend pipeline is:

1. Input guardrail
2. Intent extraction (LLM)
3. Domain guardrail
4. Template selection (or custom Cypher generation)
5. Parameter mapping
6. Cypher generation
7. Output guardrail
8. Schema validation
9. Neo4j execution
10. Path extraction + response formatting

Returned payload includes:
- Natural-language answer
- Explanation
- Executed Cypher
- Graph nodes/edges for visualization
- Tabular data rows
- Metadata (timing/counts/template/intent)

## LLM Prompting Strategy
The system uses a hybrid strategy:

### Deterministic templates first
For common intents (count, find node, ranking, etc.), predefined Cypher templates are preferred for stability.

### Custom generation when needed
For complex user questions, prompts include:
- Allowed node labels/properties
- Allowed relationships and directions
- Candidate traversal patterns
- Identifier rules (primary keys and alternates)
- Strict output format requirements

### Fallback model strategy
Primary provider is called first; fallback provider is used on provider failure.

## Guardrails and Safety
Guardrails are enforced before execution:

- Input guardrails: block prompt-injection patterns and unsafe content
- Domain guardrails: ensure query entities map to known graph domain
- Output guardrails: enforce read-only Cypher
- Schema validator: validate labels, relationship types, direction, and malformed syntax

Additional corrective rewrites are applied for common LLM mistakes:
- Arrow direction fixes
- Invalid inline OR maps to WHERE clauses
- EXISTS syntax normalization
- Invalid path patterns in WITH moved to MATCH clauses

Runtime protection:
- Provider rate-limit errors are surfaced as HTTP 429
- Query failures are logged with stage-aware diagnostics

## Session-Based Chat Behavior
- A client session ID is generated and reused
- On reload, history for the session is fetched from Supabase
- On Quit, session history is cleared and a new session starts

## Deployment Layout
Single repo, split deployment:
- Backend -> Hugging Face Space (Docker)
- Frontend -> Vercel (root directory `frontend`)

Frontend uses `VITE_API_BASE_URL` for production backend URL wiring.
