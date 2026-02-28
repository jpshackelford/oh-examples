"""Tests for the high-level metrics retrieval."""

from __future__ import annotations

import sys
from pathlib import Path


# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from oh_api import APIClient, get_conversation_metrics
from oh_api.metrics import ConversationMetrics, _extract_metrics_from_dict


class TestExtractMetrics:
    """Test the _extract_metrics_from_dict helper."""

    def test_nested_structure(self):
        """Test extracting from nested token_usage structure."""
        data = {
            "accumulated_cost": 1.5,
            "accumulated_token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "cache_read_tokens": 100,
                "cache_write_tokens": 200,
                "reasoning_tokens": 50,
                "context_window": 128000,
            },
        }

        cost, prompt, completion, cache_r, cache_w, reasoning, context = (
            _extract_metrics_from_dict(data)
        )

        assert cost == 1.5
        assert prompt == 1000
        assert completion == 500
        assert cache_r == 100
        assert cache_w == 200
        assert reasoning == 50
        assert context == 128000

    def test_flat_structure(self):
        """Test extracting from flat structure (no nested dict)."""
        data = {
            "accumulated_cost": 0.5,
            "prompt_tokens": 500,
            "completion_tokens": 100,
        }

        cost, prompt, completion, cache_r, cache_w, reasoning, context = (
            _extract_metrics_from_dict(data)
        )

        assert cost == 0.5
        assert prompt == 500
        assert completion == 100
        assert cache_r == 0  # defaults
        assert reasoning == 0


class TestConversationMetrics:
    """Test ConversationMetrics dataclass."""

    def test_total_tokens(self):
        """Test total_tokens property."""
        metrics = ConversationMetrics(
            conversation_id="test",
            title=None,
            api_version="V0",
            api_used="V0 (events)",
            accumulated_cost=1.0,
            prompt_tokens=1000,
            completion_tokens=500,
            cache_read_tokens=0,
            cache_write_tokens=0,
            reasoning_tokens=0,
            context_window=0,
        )

        assert metrics.total_tokens == 1500

    def test_to_dict(self):
        """Test to_dict serialization."""
        metrics = ConversationMetrics(
            conversation_id="test123",
            title="Test Title",
            api_version="V1",
            api_used="V1 (app-conversations)",
            accumulated_cost=2.5,
            prompt_tokens=25000,
            completion_tokens=5000,
            cache_read_tokens=1000,
            cache_write_tokens=500,
            reasoning_tokens=100,
            context_window=200000,
        )

        result = metrics.to_dict()

        assert result["conversation_id"] == "test123"
        assert result["title"] == "Test Title"
        assert result["api_version"] == "V1"
        assert result["metrics"]["accumulated_cost"] == 2.5
        assert result["metrics"]["accumulated_token_usage"]["prompt_tokens"] == 25000


class TestGetConversationMetrics:
    """Test the high-level get_conversation_metrics function."""

    def test_v0_conversation_via_events(self, client_with_fixtures: APIClient):
        """Test getting metrics for V0 conversation via events endpoint."""
        result = get_conversation_metrics(client_with_fixtures, "v0test123")

        assert result is not None
        assert result.conversation_id == "v0test123"
        assert result.api_version == "V0"
        assert result.api_used == "V0 (events)"
        assert result.accumulated_cost == 0.05
        assert result.prompt_tokens == 5000

    def test_v1_conversation_via_app_conversations(
        self, client_with_fixtures: APIClient
    ):
        """Test getting metrics for V1 conversation via app-conversations."""
        result = get_conversation_metrics(client_with_fixtures, "v1test456")

        assert result is not None
        assert result.conversation_id == "v1test456"
        assert result.api_version == "V1"
        assert result.api_used == "V1 (app-conversations)"
        assert result.accumulated_cost == 2.5
        assert result.title == "V1 Test Conversation with Metrics"

    def test_fallback_to_trajectory(self, client_with_fixtures: APIClient):
        """Test fallback to trajectory when events have no metrics."""
        result = get_conversation_metrics(client_with_fixtures, "trajectory_fallback")

        assert result is not None
        assert result.api_used == "V0 (trajectory)"
        assert result.accumulated_cost == 0.1
        assert result.reasoning_tokens == 50

    def test_not_found(self, client_with_fixtures: APIClient):
        """Test getting metrics for non-existent conversation."""
        result = get_conversation_metrics(client_with_fixtures, "notfound")

        assert result is None

    def test_v1_conversation_with_zero_metrics_in_app_conversations(
        self, client_with_fixtures: APIClient
    ):
        """Test V1 conversation where app-conversations returns 0 but events have metrics.

        This is a regression test for a bug where V1 conversations would show $0 cost
        because the /api/v1/app-conversations endpoint returns empty metrics, but the
        actual metrics are stored in ConversationStateUpdateEvent events.

        The metrics should be retrieved from:
        /api/v1/conversation/{id}/events/search -> ConversationStateUpdateEvent
        -> value.stats.usage_to_metrics.agent
        """
        result = get_conversation_metrics(client_with_fixtures, "v1_72d40619")

        assert result is not None
        assert result.conversation_id == "v1_72d40619"
        assert result.api_version == "V1"
        # The real cost should be ~$13.58, NOT $0
        assert result.accumulated_cost > 13.0, (
            f"Expected cost > $13, got ${result.accumulated_cost}. "
            "Bug: V1 metrics from events not being retrieved."
        )
        assert result.prompt_tokens > 17000000  # ~17.5M tokens
        assert result.completion_tokens > 60000  # ~64k tokens
        assert result.cache_read_tokens > 17000000  # ~17M cached
