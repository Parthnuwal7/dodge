from httpx import Timeout
from openai import OpenAI

from app.config.settings import Settings
from app.utils.logger import get_logger

logger = get_logger("llm.llm_client")


class FallbackLLMClient:
    """OpenAI-compatible client that falls back to Groq if the primary provider fails."""

    def __init__(self, primary: OpenAI, primary_model: str,
                 fallback: OpenAI | None, fallback_model: str) -> None:
        self._primary = primary
        self._primary_model = primary_model
        self._fallback = fallback
        self._fallback_model = fallback_model
        self.chat = self  # mimic OpenAI client structure

    @property
    def completions(self):
        return self

    def create(self, *, model: str = "", **kwargs):
        """Try primary, fall back to Groq on any error."""
        effective_model = model or self._primary_model
        try:
            logger.debug("Calling primary LLM (model=%s)", effective_model)
            result = self._primary.chat.completions.create(model=effective_model, **kwargs)
            content = result.choices[0].message.content if result.choices else None
            if not content and self._fallback:
                logger.warning("Primary LLM returned empty content, falling back to Groq")
                return self._fallback.chat.completions.create(model=self._fallback_model, **kwargs)
            return result
        except Exception as e:
            if not self._fallback:
                raise
            logger.warning("Primary LLM failed (%s), falling back to Groq: %s", effective_model, e)
            return self._fallback.chat.completions.create(model=self._fallback_model, **kwargs)

    @classmethod
    def from_settings(cls, settings: Settings) -> "FallbackLLMClient":
        client_timeout = Timeout(40.0, connect=10.0)
        primary = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=client_timeout,
        )

        fallback = None
        if settings.groq_api_key:
            fallback = OpenAI(
                api_key=settings.groq_api_key,
                base_url=settings.groq_base_url,
                timeout=client_timeout,
            )
            logger.info("Groq fallback configured (model: %s)", settings.groq_model)

        return cls(
            primary=primary,
            primary_model=settings.llm_model,
            fallback=fallback,
            fallback_model=settings.groq_model,
        )
