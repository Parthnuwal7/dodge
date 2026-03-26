import json
from typing import Any

from pydantic import BaseModel

from app.llm.prompt_manager import PromptManager
from app.query.execution_engine import QueryResult
from app.query.path_extractor import GraphEdge, GraphNode
from app.query.query_router import RoutedQuery
from app.utils.logger import get_logger

logger = get_logger("query.response_formatter")


class QueryResponse(BaseModel):
    answer: str
    explanation: str
    query_used: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    data: list[dict]
    metadata: dict


class ResponseFormatter:
    """Builds the final response from RoutedQuery + QueryResult."""

    def __init__(
        self,
        llm_client: Any = None,
        model: str = "",
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.prompt_manager = prompt_manager

    def format(self, routed_query: RoutedQuery, result: QueryResult) -> QueryResponse:
        answer = self._llm_answer(routed_query, result)
        explanation = self._build_explanation(routed_query)

        return QueryResponse(
            answer=answer,
            explanation=explanation,
            query_used=routed_query.cypher,
            nodes=result.graph.nodes,
            edges=result.graph.edges,
            data=self._sanitize_data(result.data),
            metadata={
                "template_name": routed_query.template_name,
                "intent_type": routed_query.intent.intent_type,
                "confidence": routed_query.intent.confidence,
                "execution_time_ms": result.execution_time_ms,
                "record_count": len(result.data),
                "node_count": len(result.graph.nodes),
                "edge_count": len(result.graph.edges),
            },
        )

    def _llm_answer(self, routed_query: RoutedQuery, result: QueryResult) -> str:
        """Try to generate a natural language answer via LLM. Falls back to hardcoded."""
        if not self.llm_client or not self.prompt_manager:
            return self._build_answer(routed_query, result)

        try:
            sanitized = self._sanitize_data(result.data)
            preview = sanitized[:10]
            results_json = json.dumps(preview, default=str, ensure_ascii=False)

            prompt = self.prompt_manager.render("response_synthesis", {
                "user_query": routed_query.intent.raw_query,
                "cypher": routed_query.cypher,
                "results_json": results_json,
                "total_count": str(len(sanitized)),
            })

            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                timeout=15,
            )
            answer = response.choices[0].message.content.strip()
            if answer:
                return answer
        except Exception as e:
            logger.warning("LLM response synthesis failed, using fallback: %s", e)

        return self._build_answer(routed_query, result)

    def _build_answer(self, routed_query: RoutedQuery, result: QueryResult) -> str:
        """Generate a human-readable answer from the query results."""
        data = result.data
        intent = routed_query.intent

        if not data:
            return "No results found for your query."

        if intent.intent_type == "count":
            # Expect a single row with a 'total' field
            total = data[0].get("total", len(data))
            label = routed_query.parameters.get("label", "nodes")
            return f"There are {total} {label} nodes."

        if intent.intent_type == "aggregate":
            row = data[0]
            agg_result = row.get("result", "N/A")
            total_nodes = row.get("total_nodes", "N/A")
            func = routed_query.parameters.get("aggregate_function", "SUM")
            prop = routed_query.parameters.get("property_name", "")
            label = routed_query.parameters.get("label", "")
            return f"The {func} of {prop} across {total_nodes} {label} nodes is {agg_result}."

        if intent.intent_type in ("find_node", "search"):
            return f"Found {len(data)} matching node(s)."

        if intent.intent_type == "find_path":
            return f"Found {len(data)} path(s) between the specified nodes."

        if intent.intent_type == "list_neighbors":
            return f"Found {len(data)} connected node(s)."

        if intent.intent_type == "flow_gaps":
            # Summarize gap types
            gap_types: dict[str, int] = {}
            for row in data:
                gap = row.get("gap_type", "Unknown")
                gap_types[gap] = gap_types.get(gap, 0) + 1
            summary = ", ".join(f"{count} {gap}" for gap, count in gap_types.items())
            return f"Found {len(data)} sales orders with incomplete flows: {summary}."

        if intent.intent_type == "find_unlinked":
            label = routed_query.parameters.get("label", "nodes")
            target = routed_query.parameters.get("target_label", "")
            return f"Found {len(data)} {label} node(s) not linked to {target}."

        if intent.intent_type == "rank":
            label = routed_query.parameters.get("label", "nodes")
            target = routed_query.parameters.get("target_label", "")
            return f"Top {len(data)} {label} node(s) ranked by connections to {target}."

        if intent.intent_type == "find_latest":
            label = routed_query.parameters.get("label", "nodes")
            direction = routed_query.parameters.get("order_direction", "DESC")
            qualifier = "most recent" if direction == "DESC" else "oldest"
            return f"Found {len(data)} {qualifier} {label} node(s)."

        if intent.intent_type == "distinct":
            prop = routed_query.parameters.get("property_name", "")
            label = routed_query.parameters.get("label", "nodes")
            count = len(data)
            values = [str(row.get("value", "")) for row in data[:20]]
            values_str = ", ".join(values)
            if count > 20:
                values_str += f", ... ({count - 20} more)"
            return f"Found {count} distinct {prop} values for {label}: {values_str}."

        return f"Query returned {len(data)} result(s)."

    def _build_explanation(self, routed_query: RoutedQuery) -> str:
        """Build a human-readable explanation of what the query does."""
        intent = routed_query.intent
        params = routed_query.parameters

        if intent.intent_type == "count":
            return f"Counting all {params.get('label', '')} nodes in the graph."

        if intent.intent_type == "find_node":
            label = params.get("label", "")
            prop = params.get("property_name", "")
            val = params.get("property_value", "")
            return f"Finding {label} nodes where {prop} = '{val}'."

        if intent.intent_type == "search":
            label = params.get("label", "")
            val = params.get("search_value", "")
            return f"Searching all properties of {label} nodes for value '{val}'."

        if intent.intent_type == "find_path":
            return (
                f"Finding the shortest path from "
                f"{params.get('start_label', '')} ({params.get('start_value', '')}) to "
                f"{params.get('end_label', '')} ({params.get('end_value', '')})."
            )

        if intent.intent_type == "list_neighbors":
            label = params.get("label", "")
            prop = params.get("property_name", "")
            val = params.get("property_value", "")
            return f"Listing all nodes connected to {label} where {prop} = '{val}'."

        if intent.intent_type == "aggregate":
            func = params.get("aggregate_function", "SUM")
            prop = params.get("property_name", "")
            label = params.get("label", "")
            return f"Computing {func} of {prop} for all {label} nodes."

        if intent.intent_type == "flow_gaps":
            return "Analyzing Order-to-Cash flow for sales orders with missing delivery, billing, journal entry, or payment steps."

        if intent.intent_type == "find_unlinked":
            label = params.get("label", "")
            rel = params.get("relationship_type", "")
            target = params.get("target_label", "")
            return f"Finding {label} nodes that have no {rel} relationship to {target}."

        if intent.intent_type == "rank":
            label = params.get("label", "")
            rel = params.get("relationship_type", "")
            target = params.get("target_label", "")
            return f"Ranking {label} nodes by number of {rel} relationships to {target}."

        if intent.intent_type == "find_latest":
            label = params.get("label", "")
            prop = params.get("order_property", "creationDate")
            direction = params.get("order_direction", "DESC")
            qualifier = "most recent" if direction == "DESC" else "oldest"
            return f"Finding {qualifier} {label} nodes ordered by {prop}."

        if intent.intent_type == "distinct":
            prop = params.get("property_name", "")
            label = params.get("label", "")
            return f"Listing distinct values of {prop} across all {label} nodes."

        if intent.intent_type == "custom":
            return f"Running a custom query generated from your question."

        return f"Executing a {intent.intent_type} query."

    @staticmethod
    def _sanitize_data(data: list[dict]) -> list[dict]:
        """Convert raw Neo4j records to JSON-serializable dicts.

        Neo4j Node/Relationship objects are flattened into the row so that
        their properties appear as regular columns.
        """
        sanitized = []
        for row in data:
            clean: dict = {}
            for key, value in row.items():
                # Neo4j Node or Relationship — flatten properties into row
                if hasattr(value, "_properties"):
                    for pk, pv in value._properties.items():
                        clean[pk] = pv
                elif hasattr(value, "items") and not isinstance(value, dict):
                    for pk, pv in value.items():
                        clean[pk] = pv
                elif isinstance(value, dict):
                    # Already a dict (e.g. from driver deserialization)
                    for pk, pv in value.items():
                        clean[pk] = pv
                else:
                    clean[key] = value
            sanitized.append(clean)
        return sanitized
