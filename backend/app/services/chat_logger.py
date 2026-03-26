from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings
from app.utils.logger import get_logger

logger = get_logger("services.chat_logger")


class SupabaseChatLogger:
    """Best-effort logger for persisting chat query interactions to Supabase."""

    def __init__(self, settings: Settings) -> None:
        self.url_set = bool(settings.supabase_url)
        self.key_set = bool(settings.supabase_service_role_key)
        self.enabled = bool(settings.supabase_url and settings.supabase_service_role_key)
        self.table_name = settings.supabase_chat_table
        self._client: Any | None = None

        if not self.enabled:
            logger.info(
                "Supabase chat logging disabled (SUPABASE_URL set=%s, SUPABASE_SERVICE_ROLE_KEY set=%s)",
                self.url_set,
                self.key_set,
            )
            return

        try:
            from supabase import create_client

            self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)
            logger.info("Supabase chat logging enabled for table '%s'", self.table_name)
        except Exception as exc:
            self.enabled = False
            self._client = None
            logger.warning("Failed to initialize Supabase chat logger: %s", exc)

    def log(
        self,
        *,
        session_id: str | None,
        question: str,
        answer: str,
        explanation: str,
        query_used: str,
        metadata: dict[str, Any],
        node_count: int,
        edge_count: int,
        record_count: int,
        status: str,
        error: str | None = None,
    ) -> None:
        """Insert a chat log row. Failures are swallowed to avoid breaking query flow."""
        if not self.enabled or self._client is None:
            return

        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "explanation": explanation,
            "query_used": query_used,
            "metadata": metadata,
            "node_count": node_count,
            "edge_count": edge_count,
            "record_count": record_count,
            "status": status,
            "error": error,
        }

        try:
            self._client.table(self.table_name).insert(payload).execute()
        except Exception as exc:
            logger.warning("Failed to write chat log to Supabase: %s", exc)

    def health(self) -> dict[str, Any]:
        """Return whether logger is configured and able to query table."""
        if not self.enabled or self._client is None:
            return {
                "enabled": False,
                "connected": False,
                "table": self.table_name,
                "message": (
                    "Supabase logger is not configured "
                    f"(SUPABASE_URL set={self.url_set}, SUPABASE_SERVICE_ROLE_KEY set={self.key_set})."
                ),
            }

        try:
            self._client.table(self.table_name).select("created_at").limit(1).execute()
            return {
                "enabled": True,
                "connected": True,
                "table": self.table_name,
                "message": "Supabase chat logging is active.",
            }
        except Exception as exc:
            return {
                "enabled": True,
                "connected": False,
                "table": self.table_name,
                "message": str(exc),
            }

    def list_session(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Return chat rows for a single session, oldest first."""
        if not self.enabled or self._client is None:
            return []

        try:
            response = (
                self._client
                .table(self.table_name)
                .select("created_at,session_id,question,answer,explanation,query_used,metadata,node_count,edge_count,record_count,status,error")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return list(getattr(response, "data", []) or [])
        except Exception as exc:
            logger.warning("Failed to read chat history from Supabase: %s", exc)
            return []

    def clear_session(self, session_id: str) -> int:
        """Delete all rows for a session and return deleted row count if available."""
        if not self.enabled or self._client is None:
            return 0

        try:
            response = (
                self._client
                .table(self.table_name)
                .delete()
                .eq("session_id", session_id)
                .execute()
            )
            deleted = list(getattr(response, "data", []) or [])
            return len(deleted)
        except Exception as exc:
            logger.warning("Failed to clear chat history from Supabase: %s", exc)
            return 0
