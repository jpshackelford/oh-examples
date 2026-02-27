"""Tests for the V0 API driver."""

from __future__ import annotations

import sys
from pathlib import Path


# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent / "conversation-metrics"
sys.path.insert(0, str(PACKAGE_DIR))

from oh_api import APIClient
from oh_api.v0 import V0Driver


class TestV0GetConversation:
    """Test V0Driver.get_conversation()."""

    def test_get_v0_conversation(self, client_with_fixtures: APIClient):
        """Test getting V0 conversation info."""
        driver = V0Driver(client_with_fixtures)
        result = driver.get_conversation("v0test123")

        assert result is not None
        assert result.conversation_id == "v0test123"
        assert result.title == "V0 Test Conversation"
        assert result.status == "completed"
        assert result.conversation_version == "V0"

    def test_get_conversation_not_found(self, client_with_fixtures: APIClient):
        """Test getting non-existent conversation returns None."""
        driver = V0Driver(client_with_fixtures)
        result = driver.get_conversation("notfound")

        assert result is None


class TestV0GetEvents:
    """Test V0Driver.get_events()."""

    def test_get_events(self, client_with_fixtures: APIClient):
        """Test getting events for a conversation."""
        driver = V0Driver(client_with_fixtures)
        result = driver.get_events("v0test123", limit=100, reverse=True)

        assert result is not None
        assert "events" in result
        assert len(result["events"]) == 2
        assert result["has_more"] is False


class TestV0FindMetrics:
    """Test V0Driver metric extraction methods."""

    def test_find_metrics_in_events(self, client_with_fixtures: APIClient):
        """Test finding metrics in events response."""
        driver = V0Driver(client_with_fixtures)
        events_response = driver.get_events("v0test123")

        assert events_response is not None
        metrics = driver.find_metrics_in_events(events_response)

        assert metrics is not None
        assert metrics["accumulated_cost"] == 0.05
        assert metrics["accumulated_token_usage"]["prompt_tokens"] == 5000

    def test_find_metrics_in_events_without_metrics(
        self, client_with_fixtures: APIClient
    ):
        """Test finding metrics when none exist."""
        driver = V0Driver(client_with_fixtures)
        events_response = driver.get_events("trajectory_fallback")

        assert events_response is not None
        metrics = driver.find_metrics_in_events(events_response)

        assert metrics is None

    def test_find_metrics_in_trajectory(self, client_with_fixtures: APIClient):
        """Test finding metrics in trajectory response."""
        driver = V0Driver(client_with_fixtures)
        trajectory = driver.get_trajectory("trajectory_fallback")

        assert trajectory is not None
        metrics = driver.find_metrics_in_trajectory(trajectory)

        assert metrics is not None
        assert metrics["accumulated_cost"] == 0.1
        assert metrics["accumulated_token_usage"]["reasoning_tokens"] == 50

    def test_find_metrics_empty_list(self):
        """Test finding metrics in empty list."""
        driver = V0Driver(None)  # type: ignore
        result = driver.find_metrics_in_trajectory({"trajectory": []})
        assert result is None

    def test_find_metrics_invalid_format(self):
        """Test finding metrics with invalid format."""
        driver = V0Driver(None)  # type: ignore
        result = driver.find_metrics_in_trajectory({"trajectory": "invalid"})
        assert result is None
