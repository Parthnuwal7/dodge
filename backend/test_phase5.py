"""Phase 5 test script. Run from backend/ with venv activated:
    python test_phase5.py
"""
from openai import OpenAI

from app.config.settings import get_settings
from app.llm.cypher_generator import CypherGenerator
from app.llm.guardrails import Guardrails
from app.llm.intent_extractor import IntentExtractor
from app.llm.prompt_manager import PromptManager
from app.llm.template_registry import QueryTemplateRegistry
from app.modeling.graph_schema import GraphSchema


def main():
    s = get_settings()

    # Load the exported graph schema
    import json
    with open("graph_schema.json", "r") as f:
        schema = GraphSchema.model_validate(json.load(f))

    print(f"Schema: {len(schema.nodes)} nodes, {len(schema.edges)} edges")

    # Setup LLM client (OpenRouter uses OpenAI-compatible API)
    llm_client = OpenAI(
        api_key=s.openrouter_api_key,
        base_url=s.openrouter_base_url,
    )

    # Setup components
    pm = PromptManager()
    guardrails = Guardrails(
        blocked_patterns=["ignore previous", "forget your instructions"],
        allowed_domains=schema.node_labels(),
    )
    extractor = IntentExtractor(pm, llm_client, s.llm_model)
    registry = QueryTemplateRegistry(s.cypher_template_dir)
    generator = CypherGenerator()

    # Test queries
    test_queries = [
        "How many sales orders are there?",
        "Show me sales order 740506",
        "Find the path from sales order 740506 to product B8907367041603",
        "What is the total net amount of all billing document headers?",
        "Show me all neighbors of business partner 310000108",
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")

        # 1. Input guardrail
        input_check = guardrails.validate_input(query)
        if not input_check.passed:
            print(f"  BLOCKED (input): {input_check.reason}")
            continue

        # 2. Extract intent
        intent = extractor.extract(query, schema)
        print(f"  Intent: {intent.intent_type} (confidence={intent.confidence})")
        print(f"  Entities: {intent.entities}")
        print(f"  Filters: {intent.filters}")

        # 3. Domain guardrail
        domain_check = guardrails.validate_domain(intent.entities)
        if not domain_check.passed:
            print(f"  BLOCKED (domain): {domain_check.reason}")
            continue

        # 4. Select template
        template = registry.select_template(intent)
        print(f"  Template: {template.name}")

        # 5. Build parameters from intent
        params = _build_params(intent, template)
        print(f"  Params: {params}")

        # 6. Generate Cypher
        try:
            cypher = generator.generate(template, params)
            print(f"  Cypher: {cypher}")
        except ValueError as e:
            print(f"  FAILED (generation): {e}")
            continue

        # 7. Output guardrail
        output_check = guardrails.validate_output(cypher)
        if not output_check.passed:
            print(f"  BLOCKED (output): {output_check.reason}")
            continue

        print("  STATUS: Ready for execution")


def _build_params(intent, template) -> dict:
    """Map intent fields to template parameters. This is a simple mapper."""
    params = {}
    filters = intent.filters

    if template.name == "count":
        params["label"] = intent.entities[0] if intent.entities else "SalesOrderHeaders"

    elif template.name == "find_node":
        params["label"] = intent.entities[0] if intent.entities else "SalesOrderHeaders"
        # Use first filter as the property filter
        if filters:
            key = next(iter(filters))
            params["property_name"] = key
            params["property_value"] = str(filters[key])
        else:
            params["property_name"] = "salesOrder"
            params["property_value"] = ""

    elif template.name == "find_path":
        entities = intent.entities
        params["start_label"] = entities[0] if len(entities) > 0 else "SalesOrderHeaders"
        params["end_label"] = entities[1] if len(entities) > 1 else "Products"
        # Try to extract start/end values from filters
        params["start_property"] = filters.get("start_property", "salesOrder")
        params["start_value"] = str(filters.get("start_value", ""))
        params["end_property"] = filters.get("end_property", "product")
        params["end_value"] = str(filters.get("end_value", ""))

    elif template.name == "list_neighbors":
        params["label"] = intent.entities[0] if intent.entities else "SalesOrderHeaders"
        if filters:
            key = next(iter(filters))
            params["property_name"] = key
            params["property_value"] = str(filters[key])
        else:
            params["property_name"] = "businessPartner"
            params["property_value"] = ""

    elif template.name == "aggregate":
        params["label"] = intent.entities[0] if intent.entities else "SalesOrderHeaders"
        params["aggregate_function"] = filters.get("aggregate_function", "SUM")
        params["property_name"] = filters.get("property_name", "totalNetAmount")

    return params


if __name__ == "__main__":
    main()
