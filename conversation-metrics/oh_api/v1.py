"""V1 API driver for OpenHands.

The V1 API is the current recommended API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oh_api.client import APIClient


@dataclass
class MetricsSnapshot:
    """Snapshot of conversation metrics from V1 API."""

    accumulated_cost: float
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    context_window: int
    model_name: str
    raw: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricsSnapshot:
        """Create MetricsSnapshot from API response dict."""
        token_usage = data.get("accumulated_token_usage", {})

        return cls(
            accumulated_cost=data.get("accumulated_cost", 0.0),
            prompt_tokens=token_usage.get("prompt_tokens", 0),
            completion_tokens=token_usage.get("completion_tokens", 0),
            cache_read_tokens=token_usage.get("cache_read_tokens", 0),
            cache_write_tokens=token_usage.get("cache_write_tokens", 0),
            reasoning_tokens=token_usage.get("reasoning_tokens", 0),
            context_window=token_usage.get("context_window", 0),
            model_name=data.get("model_name", "default"),
            raw=data,
        )


@dataclass
class AppConversation:
    """Information about a conversation from V1 API."""

    id: str
    title: str | None
    sandbox_id: str | None
    sandbox_status: str | None
    execution_status: str | None
    llm_model: str | None
    metrics: MetricsSnapshot | None
    conversation_url: str | None
    session_api_key: str | None
    raw: dict[str, Any] | None = None


@dataclass
class V1Driver:
    """Driver for V1 API endpoints.

    V1 endpoints:
    - GET /api/v1/app-conversations?ids={id} - Batch get conversations with metrics
    - GET /api/v1/app-conversations/search - Search conversations
    - GET /api/v1/conversation/{id}/events/search - Search events
    """

    client: APIClient

    def get_conversation(self, conversation_id: str) -> AppConversation | None:
        """Get conversation with metrics.

        Args:
            conversation_id: The conversation ID

        Returns:
            AppConversation or None if not found
        """
        result = self.client.get(f"/api/v1/app-conversations?ids={conversation_id}")

        if result is None:
            return None

        # Result is a list, get first item
        if not isinstance(result, list) or len(result) == 0:
            return None

        data = result[0]
        if data is None:
            return None

        metrics = None
        if data.get("metrics"):
            metrics = MetricsSnapshot.from_dict(data["metrics"])

        return AppConversation(
            id=data.get("id", conversation_id),
            title=data.get("title"),
            sandbox_id=data.get("sandbox_id"),
            sandbox_status=data.get("sandbox_status"),
            execution_status=data.get("execution_status"),
            llm_model=data.get("llm_model"),
            metrics=metrics,
            conversation_url=data.get("conversation_url"),
            session_api_key=data.get("session_api_key"),
            raw=data,
        )

    def search_events(
        self,
        conversation_id: str,
        kind: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        """Search events for a conversation.

        Args:
            conversation_id: The conversation ID
            kind: Optional event kind filter (e.g., 'TokenEvent', 'ActionEvent')
            limit: Maximum number of events to return

        Returns:
            Dict with 'items' list and 'next_page_id', or None if not found
        """
        path = f"/api/v1/conversation/{conversation_id}/events/search?limit={limit}"
        if kind:
            path += f"&kind__eq={kind}"

        result = self.client.get(path)
        if result is None or isinstance(result, list):
            return None
        return result

    def get_metrics_from_conversation(
        self,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Get metrics dict directly from conversation.

        This is a convenience method that returns the raw metrics dict
        for compatibility with existing code.

        Args:
            conversation_id: The conversation ID

        Returns:
            Raw metrics dict or None if not found
        """
        conv = self.get_conversation(conversation_id)
        if conv is None or conv.metrics is None:
            return None
        return conv.metrics.raw
