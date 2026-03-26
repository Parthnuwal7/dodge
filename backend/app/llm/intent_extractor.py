import json
from typing import Any

from pydantic import BaseModel

from app.llm.prompt_manager import PromptManager
from app.modeling.graph_schema import GraphSchema
from app.utils.logger import get_logger

logger = get_logger("llm.intent_extractor")

VALID_INTENT_TYPES = {"find_node", "search", "find_path", "list_neighbors", "aggregate", "count", "find_unlinked", "flow_gaps", "rank", "find_latest", "distinct", "custom"}


class QueryIntent(BaseModel):
    intent_type: str
    entities: list[str]
    filters: dict[str, Any]
    raw_query: str
    confidence: float


class IntentExtractor:
    def __init__(self, prompt_manager: PromptManager, llm_client: Any, model: str) -> None:
        self.prompt_manager = prompt_manager
        self.llm_client = llm_client
        self.model = model

    def extract(self, user_query: str, schema: GraphSchema) -> QueryIntent:
        """Extract intent, entities, and filters from a user query using the LLM."""
        prompt = self.prompt_manager.render("intent_extraction", {
            "node_labels": ", ".join(schema.node_labels()),
            "edge_types": ", ".join(schema.edge_types()),
            "edge_descriptions": "\n".join(schema.edge_descriptions()),
            "node_properties": "\n".join(schema.node_properties_summary()),
            "user_query": user_query,
        })

        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout=30,
        )

        raw_text = response.choices[0].message.content.strip()
        logger.debug("LLM intent response: %s", raw_text)

        parsed = self._parse_response(raw_text, user_query)
        return parsed

    def _parse_response(self, raw_text: str, user_query: str) -> QueryIntent:
        """Parse the LLM JSON response into a QueryIntent."""
        # Strip markdown code fences if present
        text = raw_text
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", raw_text)
            return QueryIntent(
                intent_type="find_node",
                entities=[],
                filters={},
                raw_query=user_query,
                confidence=0.0,
            )

        intent_type = data.get("intent_type", "find_node")
        if intent_type not in VALID_INTENT_TYPES:
            intent_type = "find_node"

        return QueryIntent(
            intent_type=intent_type,
            entities=data.get("entities", []),
            filters=data.get("filters", {}),
            raw_query=user_query,
            confidence=float(data.get("confidence", 0.5)),
        )
