"""Tests for the V1 API driver."""

from __future__ import annotations

import sys
from pathlib import Path


# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from oh_api import APIClient
from oh_api.v1 import MetricsSnapshot, V1Driver


class TestMetricsSnapshot:
    """Test MetricsSnapshot dataclass."""

    def test_from_dict_full(self):
        """Test creating MetricsSnapshot from full dict."""
        data = {
            "accumulated_cost": 2.5,
            "accumulated_token_usage": {
                "prompt_tokens": 25000,
                "completion_tokens": 5000,
                "cache_read_tokens": 10000,
                "cache_write_tokens": 5000,
                "reasoning_tokens": 500,
                "context_window": 200000,
            },
            "model_name": "claude-sonnet-4-5-20250929",
        }

        metrics = MetricsSnapshot.from_dict(data)

        assert metrics.accumulated_cost == 2.5
        assert metrics.prompt_tokens == 25000
        assert metrics.completion_tokens == 5000
        assert metrics.cache_read_tokens == 10000
        assert metrics.cache_write_tokens == 5000
        assert metrics.reasoning_tokens == 500
        assert metrics.context_window == 200000
        assert metrics.model_name == "claude-sonnet-4-5-20250929"

    def test_from_dict_partial(self):
        """Test creating MetricsSnapshot from partial dict with defaults."""
        data = {
            "accumulated_cost": 1.0,
            "accumulated_token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
            },
        }

        metrics = MetricsSnapshot.from_dict(data)

        assert metrics.accumulated_cost == 1.0
        assert metrics.prompt_tokens == 1000
        assert metrics.completion_tokens == 500
        assert metrics.cache_read_tokens == 0  # default
        assert metrics.reasoning_tokens == 0  # default
        assert metrics.model_name == "default"  # default


class TestV1GetConversation:
    """Test V1Driver.get_conversation()."""

    def test_get_v1_conversation(self, client_with_fixtures: APIClient):
        """Test getting V1 conversation with metrics."""
        driver = V1Driver(client_with_fixtures)
        result = driver.get_conversation("v1test456")

        assert result is not None
        assert result.id == "v1test456"
        assert result.title == "V1 Test Conversation with Metrics"
        assert result.llm_model == "claude-sonnet-4-5-20250929"

        assert result.metrics is not None
        assert result.metrics.accumulated_cost == 2.5
        assert result.metrics.prompt_tokens == 25000
        assert result.metrics.reasoning_tokens == 500


class TestV1GetMetricsFromConversation:
    """Test V1Driver.get_metrics_from_conversation()."""

    def test_get_metrics_raw(self, client_with_fixtures: APIClient):
        """Test getting raw metrics dict."""
        driver = V1Driver(client_with_fixtures)
        result = driver.get_metrics_from_conversation("v1test456")

        assert result is not None
        assert result["accumulated_cost"] == 2.5
        assert "accumulated_token_usage" in result


class TestV1FindMetricsInEvents:
    """Test V1Driver.find_metrics_in_events()."""

    def test_find_metrics_in_conversation_state_update_event(
        self, client_with_fixtures: APIClient
    ):
        """Test finding metrics in ConversationStateUpdateEvent."""
        driver = V1Driver(client_with_fixtures)

        # Simulate events response with ConversationStateUpdateEvent
        events_response = {
            "items": [
                {
                    "kind": "ActionEvent",
                    "id": "action-1",
                },
                {
                    "kind": "ConversationStateUpdateEvent",
                    "id": "state-1",
                    "value": {
                        "stats": {
                            "usage_to_metrics": {
                                "agent": {
                                    "accumulated_cost": 5.25,
                                    "accumulated_token_usage": {
                                        "prompt_tokens": 50000,
                                        "completion_tokens": 2000,
                                        "cache_read_tokens": 40000,
                                        "cache_write_tokens": 10000,
                                        "reasoning_tokens": 100,
                                        "context_window": 200000,
                                    },
                                }
                            }
                        }
                    },
                },
            ],
            "next_page_id": None,
        }

        result = driver.find_metrics_in_events(events_response)

        assert result is not None
        assert result["accumulated_cost"] == 5.25
        assert result["accumulated_token_usage"]["prompt_tokens"] == 50000
        assert result["accumulated_token_usage"]["cache_read_tokens"] == 40000

    def test_find_metrics_returns_none_when_no_stats(
        self, client_with_fixtures: APIClient
    ):
        """Test that find_metrics_in_events returns None when no stats present."""
        driver = V1Driver(client_with_fixtures)

        events_response = {
            "items": [
                {"kind": "ActionEvent", "id": "action-1"},
                {
                    "kind": "ConversationStateUpdateEvent",
                    "id": "state-1",
                    "value": {"some_other_key": "value"},
                },
            ],
            "next_page_id": None,
        }

        result = driver.find_metrics_in_events(events_response)
        assert result is None

    def test_find_metrics_returns_none_for_empty_events(
        self, client_with_fixtures: APIClient
    ):
        """Test that find_metrics_in_events returns None for empty events."""
        driver = V1Driver(client_with_fixtures)

        events_response = {"items": [], "next_page_id": None}

        result = driver.find_metrics_in_events(events_response)
        assert result is None
