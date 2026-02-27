"""V0 API driver for OpenHands.

The V0 API is the legacy API, deprecated since v1.0.0 and scheduled
for removal April 1, 2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oh_api.client import APIClient


@dataclass
class ConversationInfo:
    """Information about a conversation from V0 API."""

    conversation_id: str
    title: str | None
    status: str | None
    conversation_version: str
    url: str | None = None
    session_api_key: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class V0Driver:
    """Driver for V0 API endpoints.

    V0 endpoints:
    - GET /api/conversations - List conversations
    - GET /api/conversations/{id} - Get conversation info
    - GET /api/conversations/{id}/events - Get events with llm_metrics
    - GET /api/conversations/{id}/trajectory - Get trajectory with llm_metrics
    """

    client: APIClient

    def get_conversation(self, conversation_id: str) -> ConversationInfo | None:
        """Get conversation information.

        Args:
            conversation_id: The conversation ID

        Returns:
            ConversationInfo or None if not found
        """
        result = self.client.get(f"/api/conversations/{conversation_id}")

        if result is None or not isinstance(result, dict):
            return None

        return ConversationInfo(
            conversation_id=result.get("conversation_id", conversation_id),
            title=result.get("title"),
            status=result.get("status"),
            conversation_version=result.get("conversation_version", "V0"),
            url=result.get("url"),
            session_api_key=result.get("session_api_key"),
            raw=result,
        )

    def get_events(
        self,
        conversation_id: str,
        limit: int = 100,
        reverse: bool = True,
    ) -> dict[str, Any] | None:
        """Get events for a conversation.

        Events may contain llm_metrics in agent message events.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of events to return (1-100)
            reverse: If True, return newest events first

        Returns:
            Dict with 'events' list and 'has_more' boolean, or None if not found
        """
        params = f"limit={limit}&reverse={'true' if reverse else 'false'}"
        result = self.client.get(
            f"/api/conversations/{conversation_id}/events?{params}"
        )
        if result is None or isinstance(result, list):
            return None
        return result

    def get_trajectory(self, conversation_id: str) -> dict[str, Any] | None:
        """Get trajectory for a conversation.

        The trajectory contains all events and may include llm_metrics.

        Args:
            conversation_id: The conversation ID

        Returns:
            Dict with 'trajectory' list, or None if not found
        """
        result = self.client.get(f"/api/conversations/{conversation_id}/trajectory")
        if result is None or isinstance(result, list):
            return None
        return result

    def find_metrics_in_events(
        self,
        events_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Find the most recent llm_metrics in an events response.

        Args:
            events_response: Response from get_events()

        Returns:
            The llm_metrics dict if found, None otherwise
        """
        events = events_response.get("events", [])
        for event in events:
            if isinstance(event, dict) and "llm_metrics" in event:
                return event["llm_metrics"]
        return None

    def find_metrics_in_trajectory(
        self,
        trajectory_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Find the most recent llm_metrics in a trajectory response.

        Args:
            trajectory_response: Response from get_trajectory()

        Returns:
            The llm_metrics dict if found, None otherwise
        """
        # Handle both formats: {"trajectory": [...]} or direct list
        if isinstance(trajectory_response, dict):
            events = trajectory_response.get("trajectory", [])
        else:
            events = trajectory_response

        if not isinstance(events, list):
            return None

        # Iterate in reverse to find most recent metrics
        for event in reversed(events):
            if isinstance(event, dict) and "llm_metrics" in event:
                return event["llm_metrics"]
        return None
