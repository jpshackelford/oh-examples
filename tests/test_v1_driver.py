"""Tests for the V1 API driver."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent / "conversation-metrics"
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
