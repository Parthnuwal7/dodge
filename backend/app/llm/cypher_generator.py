import re

from app.llm.template_registry import QueryTemplate
from app.utils.logger import get_logger

logger = get_logger("llm.cypher_generator")


class CypherGenerator:
    """Pure parameter filling. No LLM reasoning."""

    def generate(self, template: QueryTemplate, parameters: dict) -> str:
        """Fill template placeholders with parameter values.

        Template placeholders use ${param_name} syntax.
        """
        # Validate required params are present
        missing = [p for p in template.required_params if p not in parameters]
        if missing:
            raise ValueError(
                f"Missing required parameters for template '{template.name}': {missing}. "
                f"Provided: {list(parameters.keys())}"
            )

        cypher = template.cypher

        # Replace ${param_name} placeholders
        for key, value in parameters.items():
            placeholder = f"${{{key}}}"
            if key == "where_clause":
                # Pre-built Cypher fragment — inject as-is (already escaped)
                safe_value = str(value)
            else:
                # Escape single quotes using Cypher convention (double single-quote)
                safe_value = str(value).replace("'", "''")
            cypher = cypher.replace(placeholder, safe_value)

        # Clean up invalid Cypher patterns caused by empty parameters
        # Remove property matchers with empty keys: {``: '...'}
        cypher = re.sub(r"\s*\{``: '[^']*'\}", "", cypher)
        # Remove WHERE-only lines with empty backtick property: WHERE n.`` ...
        cypher = re.sub(r"\n\s*WHERE\s+[^`]*``[^\n]*", "", cypher)
        # Remove fragments like toFloat(n.``) or n.`` within remaining lines
        cypher = re.sub(r"\w+\(\w+\(n\.``\)\)", "0", cypher)  # SUM(toFloat(n.``)) -> 0
        cypher = re.sub(r"\w+\.``", "null", cypher)  # n.`` -> null

        # Warn if unreplaced placeholders remain
        remaining = re.findall(r"\$\{(\w+)\}", cypher)
        if remaining:
            logger.warning("Unreplaced placeholders in generated Cypher: %s", remaining)

        logger.debug("Generated Cypher: %s", cypher)
        return cypher
