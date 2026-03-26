from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.llm.intent_extractor import QueryIntent

logger = get_logger("llm.template_registry")


class QueryTemplate(BaseModel):
    name: str
    cypher: str
    required_params: list[str]
    description: str


class QueryTemplateRegistry:
    """Loads .cypher files from a directory and selects templates by intent."""

    def __init__(self, template_dir: str) -> None:
        self.template_dir = Path(template_dir)
        self._templates: dict[str, QueryTemplate] = {}
        self.load_templates()

    def load_templates(self) -> None:
        """Load all .cypher files from the template directory.

        Each .cypher file must have a frontmatter header:
            -- name: find_node
            -- description: Find a node by label and property value
            -- params: label, property_name, property_value

        Followed by the Cypher template body.
        """
        if not self.template_dir.exists():
            logger.warning("Template directory not found: %s", self.template_dir)
            return

        for f in sorted(self.template_dir.glob("*.cypher")):
            try:
                template = self._parse_file(f)
                self._templates[template.name] = template
                logger.info("Loaded Cypher template: %s", template.name)
            except Exception as e:
                logger.error("Failed to parse template %s: %s", f.name, e)

        logger.info("Loaded %d Cypher templates", len(self._templates))

    def _parse_file(self, path: Path) -> QueryTemplate:
        """Parse a .cypher file with frontmatter into a QueryTemplate."""
        content = path.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        meta: dict[str, str] = {}
        body_lines: list[str] = []
        in_header = True

        for line in lines:
            if in_header and line.strip().startswith("--"):
                # Parse -- key: value
                match = re.match(r"^--\s*(\w+)\s*:\s*(.+)$", line.strip())
                if match:
                    meta[match.group(1).strip()] = match.group(2).strip()
            else:
                in_header = False
                body_lines.append(line)

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        params_str = meta.get("params", "")
        required_params = [p.strip() for p in params_str.split(",") if p.strip()]
        cypher = "\n".join(body_lines).strip()

        return QueryTemplate(
            name=name,
            cypher=cypher,
            required_params=required_params,
            description=description,
        )

    def get_template(self, name: str) -> QueryTemplate:
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found. Available: {list(self._templates.keys())}")
        return self._templates[name]

    def select_template(self, intent: QueryIntent) -> QueryTemplate:
        """Select the best template for a given intent.

        Matching strategy:
        1. Exact match on intent_type == template name
        2. Fallback to first template whose name contains the intent_type
        3. Default to find_node if available
        """
        # Exact match
        if intent.intent_type in self._templates:
            return self._templates[intent.intent_type]

        # Partial match
        for name, template in self._templates.items():
            if intent.intent_type in name or name in intent.intent_type:
                return template

        # Default fallback
        if "find_node" in self._templates:
            logger.warning(
                "No template match for intent '%s', falling back to find_node",
                intent.intent_type,
            )
            return self._templates["find_node"]

        raise KeyError(
            f"No template found for intent '{intent.intent_type}' "
            f"and no fallback available. Templates: {list(self._templates.keys())}"
        )

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())
