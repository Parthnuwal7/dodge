import re

from pydantic import BaseModel

from app.config.constants import BLOCKED_CYPHER_KEYWORDS, MAX_QUERY_LENGTH
from app.utils.logger import get_logger

logger = get_logger("llm.guardrails")


class GuardrailResult(BaseModel):
    passed: bool
    reason: str | None = None
    rejection_type: str | None = None  # "blocked_pattern", "off_domain", "unsafe_cypher"


class Guardrails:
    def __init__(
        self,
        blocked_patterns: list[str] | None = None,
        allowed_domains: list[str] | None = None,
    ) -> None:
        self.blocked_patterns = blocked_patterns or []
        self.allowed_domains = allowed_domains or []

    def validate_input(self, user_query: str) -> GuardrailResult:
        """Validate user query before sending to LLM."""
        # Length check
        if len(user_query) > MAX_QUERY_LENGTH:
            return GuardrailResult(
                passed=False,
                reason=f"Query exceeds maximum length of {MAX_QUERY_LENGTH} characters",
                rejection_type="blocked_pattern",
            )

        # Empty check
        if not user_query.strip():
            return GuardrailResult(
                passed=False,
                reason="Query is empty",
                rejection_type="blocked_pattern",
            )

        # Check for blocked patterns (e.g. prompt injection attempts)
        query_lower = user_query.lower()
        for pattern in self.blocked_patterns:
            if pattern.lower() in query_lower:
                logger.warning("Blocked input pattern detected: %s", pattern)
                return GuardrailResult(
                    passed=False,
                    reason=f"Query contains blocked pattern",
                    rejection_type="blocked_pattern",
                )

        return GuardrailResult(passed=True)

    def validate_domain(self, entities: list[str]) -> GuardrailResult:
        """Validate that extracted entities belong to known domain."""
        if not self.allowed_domains:
            return GuardrailResult(passed=True)

        allowed_lower = {d.lower() for d in self.allowed_domains}
        unknown = [e for e in entities if e.lower() not in allowed_lower]

        if unknown:
            return GuardrailResult(
                passed=False,
                reason=f"Unknown entities: {unknown}. Valid: {self.allowed_domains}",
                rejection_type="off_domain",
            )

        return GuardrailResult(passed=True)

    def validate_output(self, cypher: str) -> GuardrailResult:
        """Validate generated Cypher before execution."""
        cypher_upper = cypher.upper()

        for keyword in BLOCKED_CYPHER_KEYWORDS:
            if keyword.upper() in cypher_upper:
                logger.warning("Blocked Cypher keyword detected: %s", keyword)
                return GuardrailResult(
                    passed=False,
                    reason=f"Generated Cypher contains blocked operation: {keyword}",
                    rejection_type="unsafe_cypher",
                )

        # Block multiple statements (injection via semicolons)
        if ";" in cypher:
            return GuardrailResult(
                passed=False,
                reason="Multiple Cypher statements not allowed",
                rejection_type="unsafe_cypher",
            )

        # Must start with a read operation
        stripped = cypher.strip().upper()
        if not any(stripped.startswith(kw) for kw in ("MATCH", "OPTIONAL MATCH", "WITH", "UNWIND", "RETURN", "CALL {")):
            return GuardrailResult(
                passed=False,
                reason="Cypher must start with a read operation (MATCH, RETURN, etc.)",
                rejection_type="unsafe_cypher",
            )

        return GuardrailResult(passed=True)
