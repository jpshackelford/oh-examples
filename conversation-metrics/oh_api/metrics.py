"""High-level metrics retrieval with automatic API version selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oh_api.client import APIClient
from oh_api.v0 import V0Driver
from oh_api.v1 import V1Driver


@dataclass
class ConversationMetrics:
    """Metrics for a conversation."""

    conversation_id: str
    title: str | None
    api_version: str
    api_used: str
    accumulated_cost: float
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    context_window: int
    raw_metrics: dict[str, Any] | None = None

    @property
    def total_tokens(self) -> int:
        """Total tokens (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "conversation_id": self.conversation_id,
            "title": self.title,
            "api_version": self.api_version,
            "api_used": self.api_used,
            "metrics": {
                "accumulated_cost": self.accumulated_cost,
                "accumulated_token_usage": {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "cache_read_tokens": self.cache_read_tokens,
                    "cache_write_tokens": self.cache_write_tokens,
                    "reasoning_tokens": self.reasoning_tokens,
                    "context_window": self.context_window,
                },
            },
        }


def _extract_metrics_from_dict(
    metrics: dict[str, Any],
) -> tuple[float, int, int, int, int, int, int]:
    """Extract metric values from a metrics dict.

    Handles both nested (accumulated_token_usage) and flat structures.

    Returns:
        Tuple of (cost, prompt, completion, cache_read, cache_write, reasoning, context)
    """
    cost = metrics.get("accumulated_cost", 0.0)

    # Try nested structure first
    token_usage = metrics.get("accumulated_token_usage", {})
    if not token_usage and "prompt_tokens" in metrics:
        # Flat structure
        token_usage = metrics

    return (
        cost,
        token_usage.get("prompt_tokens", 0),
        token_usage.get("completion_tokens", 0),
        token_usage.get("cache_read_tokens", 0),
        token_usage.get("cache_write_tokens", 0),
        token_usage.get("reasoning_tokens", 0),
        token_usage.get("context_window", 0),
    )


def _has_nonzero_metrics(metrics: dict[str, Any]) -> bool:
    """Check if metrics dict has any non-zero values.

    Used to detect when /api/v1/app-conversations returns empty metrics
    and we need to fall back to events endpoint.

    Args:
        metrics: Raw metrics dict from API

    Returns:
        True if accumulated_cost > 0 or any token count > 0
    """
    if metrics.get("accumulated_cost", 0.0) > 0:
        return True

    token_usage = metrics.get("accumulated_token_usage", {})
    if not token_usage:
        token_usage = metrics

    return (
        token_usage.get("prompt_tokens", 0) > 0
        or token_usage.get("completion_tokens", 0) > 0
    )


def get_conversation_metrics(
    client: APIClient,
    conversation_id: str,
) -> ConversationMetrics | None:
    """Get metrics for a conversation, automatically selecting the best API.

    Strategy:
    1. Get conversation info from V0 API to determine version
    2. For V1 conversations: Try V1 API first (has metrics in response)
    3. For V0 conversations or if V1 fails: Use V0 events endpoint
    4. Fallback: Use V0 trajectory endpoint

    Args:
        client: API client instance
        conversation_id: The conversation ID

    Returns:
        ConversationMetrics or None if conversation not found
    """
    v0 = V0Driver(client)
    v1 = V1Driver(client)

    # Step 1: Get conversation info to determine version
    conv_info = v0.get_conversation(conversation_id)
    if conv_info is None:
        return None

    version = conv_info.conversation_version
    title = conv_info.title
    metrics: dict[str, Any] | None = None
    api_used: str | None = None

    # Step 2: For V1 conversations, try V1 API first
    if version == "V1":
        v1_metrics = v1.get_metrics_from_conversation(conversation_id)
        if v1_metrics and _has_nonzero_metrics(v1_metrics):
            metrics = v1_metrics
            api_used = "V1 (app-conversations)"
            # Update title from V1 response if available
            v1_conv = v1.get_conversation(conversation_id)
            if v1_conv and v1_conv.title:
                title = v1_conv.title

    # Step 2b: For V1 conversations, if app-conversations returned zero metrics,
    # try getting metrics from ConversationStateUpdateEvent in events
    if version == "V1" and metrics is None:
        v1_events_metrics = v1.get_metrics_from_events(conversation_id)
        if v1_events_metrics:
            metrics = v1_events_metrics
            api_used = "V1 (events)"
            # Update title from V1 response if available
            v1_conv = v1.get_conversation(conversation_id)
            if v1_conv and v1_conv.title:
                title = v1_conv.title

    # Step 3: Try V0 events endpoint
    if metrics is None:
        events_response = v0.get_events(conversation_id, limit=100, reverse=True)
        if events_response:
            metrics = v0.find_metrics_in_events(events_response)
            if metrics:
                api_used = "V0 (events)"

    # Step 4: Fallback to trajectory
    if metrics is None:
        trajectory_response = v0.get_trajectory(conversation_id)
        if trajectory_response:
            metrics = v0.find_metrics_in_trajectory(trajectory_response)
            if metrics:
                api_used = "V0 (trajectory)"

    if metrics is None or api_used is None:
        return None

    # Extract values
    cost, prompt, completion, cache_read, cache_write, reasoning, context = (
        _extract_metrics_from_dict(metrics)
    )

    return ConversationMetrics(
        conversation_id=conversation_id,
        title=title,
        api_version=version,
        api_used=api_used,
        accumulated_cost=cost,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
        context_window=context,
        raw_metrics=metrics,
    )
