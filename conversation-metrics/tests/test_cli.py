"""Tests for the CLI module."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


# Add the parent directory (conversation-metrics) to the path
PACKAGE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from oh_api.cli import format_metrics, main, run_metrics
from oh_api.metrics import ConversationMetrics


def make_metrics(**kwargs) -> ConversationMetrics:
    """Helper to create ConversationMetrics with defaults."""
    defaults = {
        "conversation_id": "test123",
        "title": None,
        "api_version": "v0",
        "api_used": "events",
        "accumulated_cost": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "context_window": 0,
    }
    defaults.update(kwargs)
    return ConversationMetrics(**defaults)


class TestFormatMetrics:
    """Tests for format_metrics function."""

    def test_basic_formatting(self) -> None:
        """Test basic metrics formatting."""
        metrics = make_metrics(
            conversation_id="test123",
            accumulated_cost=0.05,
            prompt_tokens=1000,
            completion_tokens=500,
        )

        output = format_metrics(metrics)

        assert "test123" in output
        assert "$0.050000" in output
        assert "1,000" in output
        assert "500" in output
        assert "1,500" in output  # total tokens
        assert "v0" in output

    def test_formatting_with_title(self) -> None:
        """Test formatting includes title when present."""
        metrics = make_metrics(
            conversation_id="test123",
            title="My Test Conversation",
            accumulated_cost=0.01,
            prompt_tokens=100,
            completion_tokens=50,
            api_version="v1",
            api_used="app-conversations",
        )

        output = format_metrics(metrics)

        assert "My Test Conversation" in output

    def test_formatting_with_cache_tokens(self) -> None:
        """Test formatting shows cache info when present."""
        metrics = make_metrics(
            conversation_id="test123",
            accumulated_cost=0.01,
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=200,
            cache_write_tokens=100,
            api_version="v1",
            api_used="app-conversations",
        )

        output = format_metrics(metrics)

        assert "Cache" in output
        assert "200" in output
        assert "100" in output

    def test_formatting_with_reasoning_tokens(self) -> None:
        """Test formatting shows reasoning tokens when present."""
        metrics = make_metrics(
            conversation_id="test123",
            accumulated_cost=0.01,
            prompt_tokens=100,
            completion_tokens=50,
            reasoning_tokens=300,
            api_version="v1",
            api_used="app-conversations",
        )

        output = format_metrics(metrics)

        assert "Reasoning" in output
        assert "300" in output


class TestRunMetrics:
    """Tests for run_metrics function."""

    def test_not_found_returns_error(self) -> None:
        """Test that not found conversation returns exit code 1."""
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            with patch("oh_api.cli.get_conversation_metrics") as mock_get:
                mock_get.return_value = None  # Simulate not found

                result = run_metrics(
                    base_url="https://app.all-hands.dev",
                    conversation_id="notfound",
                    api_key="test-key",
                )

        assert result == 1
        assert "not found" in stderr.getvalue().lower()

    def test_json_output(self) -> None:
        """Test JSON output format."""
        stdout = StringIO()

        with patch("sys.stdout", stdout):
            with patch("oh_api.cli.APIClient"):
                with patch("oh_api.cli.get_conversation_metrics") as mock_get:
                    mock_get.return_value = make_metrics(
                        conversation_id="test123",
                        accumulated_cost=0.05,
                        prompt_tokens=1000,
                        completion_tokens=500,
                    )

                    result = run_metrics(
                        base_url="https://app.all-hands.dev",
                        conversation_id="test123",
                        api_key="test-key",
                        output_json=True,
                    )

        assert result == 0
        output = stdout.getvalue()
        data = json.loads(output)
        assert data["conversation_id"] == "test123"
        assert data["metrics"]["accumulated_cost"] == 0.05

    def test_formatted_output(self) -> None:
        """Test formatted (non-JSON) output."""
        stdout = StringIO()

        with patch("sys.stdout", stdout):
            with patch("oh_api.cli.APIClient"):
                with patch("oh_api.cli.get_conversation_metrics") as mock_get:
                    mock_get.return_value = make_metrics(
                        conversation_id="test123",
                        accumulated_cost=0.05,
                        prompt_tokens=1000,
                        completion_tokens=500,
                    )

                    result = run_metrics(
                        base_url="https://app.all-hands.dev",
                        conversation_id="test123",
                        api_key="test-key",
                        output_json=False,
                    )

        assert result == 0
        output = stdout.getvalue()
        assert "test123" in output
        assert "─" in output  # Box drawing characters


class TestMain:
    """Tests for main() CLI entry point."""

    def test_missing_api_key_exits_with_error(self) -> None:
        """Test that missing API key shows error and exits."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.argv", ["oh-metrics", "test123"]):
                with pytest.raises(SystemExit) as exc_info:
                    with patch("sys.stderr", StringIO()):
                        main()

                assert exc_info.value.code == 1

    def test_api_key_from_env(self) -> None:
        """Test that API key is read from environment."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key-from-env"}):
            with patch("sys.argv", ["oh-metrics", "test123"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit) as exc_info:
                        main()

                    # Verify run_metrics was called with the env API key
                    mock_run.assert_called_once()
                    call_args = mock_run.call_args
                    assert call_args[0][2] == "test-key-from-env"  # api_key arg
                    assert exc_info.value.code == 0

    def test_api_key_from_argument(self) -> None:
        """Test that --api-key argument overrides environment."""
        with patch.dict("os.environ", {"OH_API_KEY": "env-key"}):
            with patch("sys.argv", ["oh-metrics", "test123", "--api-key", "arg-key"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit) as exc_info:
                        main()

                    call_args = mock_run.call_args
                    assert call_args[0][2] == "arg-key"  # api_key arg
                    assert exc_info.value.code == 0

    def test_json_flag(self) -> None:
        """Test --json flag is passed correctly."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key"}):
            with patch("sys.argv", ["oh-metrics", "test123", "--json"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit):
                        main()

                    call_args = mock_run.call_args
                    assert call_args[0][3] is True  # output_json arg

    def test_log_api_calls_flag(self) -> None:
        """Test --log-api-calls flag is passed correctly."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key"}):
            with patch("sys.argv", ["oh-metrics", "test123", "--log-api-calls"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit):
                        main()

                    call_args = mock_run.call_args
                    assert call_args[0][4] is True  # log_api_calls arg

    def test_conversation_id_normalization(self) -> None:
        """Test that dashes are removed from conversation IDs."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key"}):
            with patch("sys.argv", ["oh-metrics", "abc-123-def-456"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit):
                        main()

                    call_args = mock_run.call_args
                    assert call_args[0][1] == "abc123def456"  # conversation_id

    def test_custom_base_url(self) -> None:
        """Test --base-url argument is passed correctly."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key"}):
            with patch(
                "sys.argv",
                ["oh-metrics", "test123", "--base-url", "https://custom.example.com"],
            ):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 0
                    with pytest.raises(SystemExit):
                        main()

                    call_args = mock_run.call_args
                    assert call_args[0][0] == "https://custom.example.com"  # base_url

    def test_exit_code_propagation(self) -> None:
        """Test that run_metrics exit code is propagated."""
        with patch.dict("os.environ", {"OH_API_KEY": "test-key"}):
            with patch("sys.argv", ["oh-metrics", "test123"]):
                with patch("oh_api.cli.run_metrics") as mock_run:
                    mock_run.return_value = 1  # Simulate error
                    with pytest.raises(SystemExit) as exc_info:
                        main()

                    assert exc_info.value.code == 1
