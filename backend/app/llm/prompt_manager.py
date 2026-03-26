from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger("llm.prompt_manager")

# Built-in prompt templates keyed by name
_BUILTIN_TEMPLATES: dict[str, str] = {
    "intent_extraction": (
        "You are a query analysis engine for a graph database.\n"
        "\n"
        "Available node labels: {node_labels}\n"
        "Available relationship types: {edge_types}\n"
        "\n"
        "Graph structure (FromNode -[RELATIONSHIP]-> ToNode):\n"
        "{edge_descriptions}\n"
        "\n"
        "Node properties (PRIMARY KEY and other properties):\n"
        "{node_properties}\n"
        "\n"
        "Given the user query below, extract:\n"
        "1. intent_type: one of [find_node, search, find_path, list_neighbors, aggregate, count, find_unlinked, flow_gaps, rank, find_latest, distinct, custom]\n"
        "2. entities: list of node labels referenced (must be from the available labels)\n"
        "3. filters: key-value pairs for filtering. Property names MUST be exact property names from the node properties listed above.\n"
        "4. confidence: float 0-1 indicating how confident you are\n"
        "\n"
        "Intent type guide:\n"
        "- find_node: Find specific nodes by label filtered by a KNOWN property value. "
        "The filter property MUST exist on that node type (check the properties list above). "
        "Example: to find JournalEntry by reference document 91150187, use entities: [JournalEntry], "
        "filters: {{referenceDocument: '91150187'}}.\n"
        "- search: Use when the user provides an ID or value but you are NOT SURE which property it belongs to, "
        "or when the value could match multiple properties. Set filters.search_value to the value. "
        "This searches across ALL properties of the node type. Prefer this over find_node when uncertain.\n"
        "- find_path: Find shortest path between two node types. Set filters with start/end property and value.\n"
        "- list_neighbors: List nodes connected to a specific node. Use exact property names in filters.\n"
        "- aggregate: Compute SUM/AVG/MIN/MAX on a SPECIFIC numeric property of nodes (e.g. 'total net amount of invoices'). "
        "Only use when the query names a specific numeric property. Set filters.property_name to the exact property.\n"
        "- count: Count nodes of a given label (e.g. 'how many orders')\n"
        "- find_unlinked: Find nodes that are MISSING a relationship (e.g. 'orders without deliveries'). "
        "Set filters.relationship_type and filters.target_label. "
        "Use the graph structure above to pick the correct relationship and target.\n"
        "- flow_gaps: Analyze the Order-to-Cash flow for broken/incomplete processes "
        "(e.g. 'delivered but not billed', 'incomplete flows', 'missing payments'). No filters needed.\n"
        "- rank: Use when asking 'which X has the most/least/highest number of Y' — ranks nodes by "
        "relationship count to another type. ALWAYS include BOTH node types in entities. "
        "Set filters.relationship_type and filters.target_label using the graph structure above. "
        "Only use relationships that DIRECTLY connect to the first entity. "
        "Example: 'customers with most orders' → entities: [Customer, SalesOrder], "
        "filters: {{relationship_type: PLACED_ORDER, target_label: SalesOrder}}.\n"
        "- distinct: List unique/distinct values of a property across nodes. "
        "Trigger words: 'types', 'kinds', 'different', 'unique', 'categories', 'distinct'. "
        "Set filters.property_name to the property to enumerate. "
        "Example: 'what types of plants are there' → entities: [Plant], "
        "filters: {{property_name: 'plantCategory'}}.\n"
        "- find_latest: Find the most recent or oldest nodes (e.g. 'last order', 'latest invoice', 'first delivery'). "
        "Set filters.order_property to the date field (usually 'creationDate') and "
        "filters.order_direction to 'DESC' for latest or 'ASC' for oldest.\n"
        "- custom: Use for queries that involve TRAVERSING RELATIONSHIPS between node types. "
        "This includes:\n"
        "  * Finding info about one entity via another (e.g. 'who ordered 740582' = Customer via PLACED_ORDER → SalesOrder)\n"
        "  * Filtering one entity type by a property of a related entity (e.g. 'orders from customer Nelson')\n"
        "  * Any query where the filter value belongs to a DIFFERENT node type than what's being asked about\n"
        "  * Multi-hop queries (e.g. 'products in delivery 800123', 'payments for order 740506')\n"
        "  * Aggregations across relationships (e.g. 'total invoice amount for customer X')\n"
        "When using custom, set filters.description to a brief description of what the query needs.\n"
        "\n"
        "CRITICAL RULES:\n"
        "- NEVER use find_node with a property that does NOT exist on that node type. "
        "For example, Customer does NOT have a 'salesOrder' property — use 'custom' instead to traverse the PLACED_ORDER relationship.\n"
        "- Always verify the filter property exists on the target entity before choosing find_node.\n"
        "- When in doubt between find_node and custom, choose custom — it handles all cases.\n"
        "- Always use exact property names from the node properties list. Never invent property names.\n"
        "\n"
        "Respond ONLY with valid JSON. No explanation.\n"
        "\n"
        "User query: {user_query}\n"
        "\n"
        "JSON response:"
    ),
    "cypher_explanation": (
        "Given this Cypher query:\n"
        "{cypher}\n"
        "\n"
        "Explain in one plain-English sentence what this query does."
    ),
    "cypher_generation": (
        "You are a Neo4j Cypher query expert for a business process graph database.\n"
        "\n"
        "Graph schema:\n"
        "Node labels and properties:\n"
        "{node_properties}\n"
        "\n"
        "Relationships:\n"
        "{edge_details}\n"
        "\n"
        "Candidate traversal patterns (generated from schema path search):\n"
        "{candidate_paths}\n"
        "\n"
        "Intent hints (from intent extraction):\n"
        "{intent_hints}\n"
        "\n"
        "PATH SELECTION RULES (CRITICAL — violations will be rejected):\n"
        "- COPY the candidate traversal pattern directly into your MATCH clause\n"
        "- Arrow directions (<- vs ->) are MANDATORY — they reflect the actual graph structure\n"
        "- If a candidate path shows (:`Product`)<-[:CONTAINS]-(:`SalesOrder`), you MUST write:\n"
        "  MATCH (p:`Product`)<-[:CONTAINS]-(so:`SalesOrder`)   ← correct\n"
        "  MATCH (p:`Product`)-[:CONTAINS]->(so:`SalesOrder`)   ← WRONG (reversed)\n"
        "- NEVER invent relationships between nodes. If no candidate path connects A to B, "
        "they are NOT directly connected\n"
        "- If multiple candidate paths exist, prefer the shortest one matching the user question\n"
        "\n"
        "PRIMARY KEY RULES (CRITICAL):\n"
        "Each node has a PRIMARY KEY field listed above. You MUST:\n"
        "- Use the EXACT PRIMARY KEY field name when matching identifiers\n"
        "- NEVER use 'id' as a property — it does NOT exist in the graph\n"
        "- Example: Product's PRIMARY KEY is `product`, so:\n"
        "  Correct: MATCH (p:`Product` {{`product`: '<product_id>'}})\n"
        "  WRONG:   MATCH (p:`Product` {{id: '<product_id>'}})\n"
        "  WRONG:   MATCH (p:`Product` {{`productGroup`: '<product_id>'}})\n"
        "\n"
        "IDENTIFIER MATCHING:\n"
        "Entities may have MULTIPLE identifier fields. When matching user input:\n"
        "- Product: PRIMARY KEY `product` (internal/system ID), "
        "alternate `productOldId` (legacy/external ID)\n"
        "- Customer: PRIMARY KEY `businessPartner`, alternate `businessPartnerName`\n"
        "For Product identifiers starting with 'ABC-' → use `productOldId`.\n"
        "For Product identifiers starting with 'S' or numeric → use `product`.\n"
        "When unsure, use OR matching:\n"
        "  MATCH (p:`Product`) WHERE p.`product` = 'X' OR p.`productOldId` = 'X'\n"
        "DO NOT guess property names. DO NOT use 'id'.\n"
        "\n"
        "MULTI-HOP QUERIES:\n"
        "- ALWAYS use the candidate traversal patterns above as your MATCH skeleton\n"
        "- Two nodes that are not directly connected require intermediate hops\n"
        "- To go FROM a target node BACK to its source, use the reverse arrow: <-[:REL]-\n"
        "- Example: if candidate path is (:`Product`)<-[:CONTAINS]-(:`SalesOrder`)<-[:PLACED_ORDER]-(:`Customer`)\n"
        "  then write: MATCH (p:`Product`)<-[:CONTAINS]-(so:`SalesOrder`)<-[:PLACED_ORDER]-(c:`Customer`)\n"
        "- NEVER skip intermediate nodes. If Product and Customer are only connected via SalesOrder, "
        "you MUST include SalesOrder in the path\n"
        "\n"
        "SYNTAX RULES:\n"
        "- Write a READ-ONLY Cypher query. No CREATE, DELETE, SET, MERGE, DROP.\n"
        "- Use ONLY the node labels, relationship types, and property names listed above.\n"
        "- Use backtick-quoted labels and property names: (n:`SalesOrder`), n.`salesOrder`\n"
        "- Add LIMIT 500 unless the query is an aggregation.\n"
        "- All property values are stored as strings.\n"
        "- CONTAINS is a Cypher OPERATOR: n.`prop` CONTAINS 'value'. "
        "WRONG: CONTAINS(n.`prop`, 'value').\n"
        "- Return meaningful properties in RETURN — not raw node objects.\n"
        "- Use UNIQUE variable names. Never reuse the same variable for a node and a relationship.\n"
        "  Correct: MATCH (c:`Customer`)-[r:PLACED_ORDER]->(o:`SalesOrder`)\n"
        "  WRONG:   MATCH (c:`Customer`)-[so:PLACED_ORDER]->(so:`SalesOrder`)\n"
        "- Variable naming: nodes = lowercase first letter of label (c, o, d, i, p, pl), "
        "relationships = r, r1, r2.\n"
        "\n"
        "User query: {user_query}\n"
        "\n"
        "Respond with ONLY the Cypher query. No explanation, no markdown fences."
    ),
    "response_synthesis": (
        "You are a data analyst assistant for a business process graph database "
        "(SAP Order-to-Cash: Customers, Sales Orders, Deliveries, Invoices, Journal Entries, Payments, Products, Plants).\n"
        "\n"
        "The user asked: {user_query}\n"
        "\n"
        "The following Cypher query was executed:\n"
        "{cypher}\n"
        "\n"
        "Here are the results (up to 10 rows):\n"
        "{results_json}\n"
        "\n"
        "Total result count: {total_count}\n"
        "\n"
        "Using ONLY the data above, write a concise natural language answer to the user's question. "
        "Be specific — include actual values, names, and numbers from the results. "
        "If the results are empty, say so clearly. "
        "Do NOT make up data that is not in the results. "
        "Keep it under 3 sentences unless a list is needed."
    ),
}


class PromptManager:
    def __init__(self, template_dir: str | None = None) -> None:
        self._templates: dict[str, str] = dict(_BUILTIN_TEMPLATES)
        if template_dir:
            self._load_from_dir(template_dir)

    def _load_from_dir(self, template_dir: str) -> None:
        """Load .txt prompt templates from a directory."""
        path = Path(template_dir)
        if not path.exists():
            logger.warning("Prompt template directory not found: %s", path)
            return
        for f in path.glob("*.txt"):
            name = f.stem
            self._templates[name] = f.read_text(encoding="utf-8")
            logger.info("Loaded prompt template: %s", name)

    def get_template(self, name: str) -> str:
        if name not in self._templates:
            raise KeyError(f"Prompt template '{name}' not found. Available: {list(self._templates.keys())}")
        return self._templates[name]

    def render(self, name: str, context: dict) -> str:
        template = self.get_template(name)
        return template.format(**context)
