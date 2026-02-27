"""Tests for the conversation-metrics CLI tool."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch


# Load the oh-metrics module dynamically (it doesn't have .py extension)
def load_oh_metrics():
    module_path = Path(__file__).parent.parent / "conversation-metrics" / "oh-metrics"
    loader = importlib.machinery.SourceFileLoader("oh_metrics", str(module_path))
    spec = importlib.util.spec_from_loader("oh_metrics", loader)
    if spec is None:
        raise ImportError("Could not load oh-metrics module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["oh_metrics"] = module
    loader.exec_module(module)
    return module


oh_metrics = load_oh_metrics()


class TestFormatMetrics:
    """Tests for the format_metrics function."""

    def test_format_basic_metrics(self):
        """Test formatting basic metrics with cost and tokens."""
        metrics = {
            "accumulated_cost": 0.123456,
            "accumulated_token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        }

        result = oh_metrics.format_metrics(metrics, "test123", "V0", "Test Title")

        assert "test123" in result
        assert "Test Title" in result
        assert "$0.123456" in result
        assert "1,000" in result
        assert "500" in result
        assert "1,500" in result  # total

    def test_format_metrics_with_cache(self):
        """Test formatting metrics that include cache tokens."""
        metrics = {
            "accumulated_cost": 1.5,
            "accumulated_token_usage": {
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
                "cache_read_tokens": 3000,
                "cache_write_tokens": 2000,
            },
        }

        result = oh_metrics.format_metrics(metrics, "abc", "V1", None)

        assert "Cache read:" in result
        assert "3,000" in result
        assert "Cache write:" in result
        assert "2,000" in result

    def test_format_metrics_with_reasoning_tokens(self):
        """Test formatting metrics with reasoning tokens."""
        metrics = {
            "accumulated_cost": 0.5,
            "accumulated_token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 200,
            },
        }

        result = oh_metrics.format_metrics(metrics, "xyz", "V1", None)

        assert "Reasoning tokens" in result
        assert "200" in result

    def test_format_metrics_flat_structure(self):
        """Test formatting metrics with flat token structure (no nested dict)."""
        metrics = {
            "accumulated_cost": 0.1,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        result = oh_metrics.format_metrics(metrics, "flat123", "V0", None)

        assert "$0.100000" in result
        assert "100" in result


class TestMakeRequest:
    """Tests for the make_request function."""

    def test_make_request_success(self):
        """Test successful API request."""
        mock_response = json.dumps({"status": "ok"}).encode()

        with patch.object(oh_metrics, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                mock_response
            )
            result = oh_metrics.make_request("https://example.com/api", "test-key")

        assert result == {"status": "ok"}

    def test_make_request_404_returns_none(self):
        """Test that 404 errors return None instead of raising."""
        from email.message import Message
        from urllib.error import HTTPError

        headers = Message()
        with patch.object(oh_metrics, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://example.com", 404, "Not Found", headers, None
            )
            result = oh_metrics.make_request("https://example.com/api", "test-key")

        assert result is None


class TestMainFunction:
    """Tests for the main CLI function."""

    def test_missing_api_key_prints_error(self, capsys):
        """Test that missing API key prints error message."""
        test_args = ["oh-metrics", "test-conversation-id"]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {}, clear=True):
                try:
                    oh_metrics.main()
                except SystemExit as e:
                    assert e.code == 1

        captured = capsys.readouterr()
        assert "No API key provided" in captured.err

    def test_conversation_id_normalized(self):
        """Test that conversation IDs with dashes are normalized."""
        test_args = ["oh-metrics", "abc-def-123", "--api-key", "test"]

        with patch.object(sys, "argv", test_args):
            with patch.object(oh_metrics, "get_metrics") as mock_get:
                mock_get.return_value = 0
                try:
                    oh_metrics.main()
                except SystemExit:
                    pass
                # Verify the ID was normalized (dashes removed)
                call_args = mock_get.call_args
                assert call_args[0][1] == "abcdef123"
