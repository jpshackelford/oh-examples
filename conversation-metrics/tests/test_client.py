"""Tests for the APIClient."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from oh_api import APIClient, APIError


class TestAPIClientBasics:
    """Test basic APIClient functionality."""

    def test_client_creation(self):
        """Test client can be created with minimal parameters."""
        client = APIClient(
            base_url="https://example.com/",
            api_key="test-key",
        )
        assert client.base_url == "https://example.com"  # trailing slash removed
        assert client.api_key == "test-key"
        assert client.log_api_calls is False

    def test_client_with_logging(self, tmp_path: Path):
        """Test client can be created with logging enabled."""
        client = APIClient(
            base_url="https://example.com",
            api_key="test-key",
            log_api_calls=True,
            log_dir=tmp_path / "logs",
        )
        assert client.log_api_calls is True
        assert client.log_dir is not None
        assert client.log_dir.exists()


class TestAPIClientFixtures:
    """Test APIClient with fixture support."""

    def test_fixture_loading(self, client_with_fixtures: APIClient):
        """Test that fixtures are loaded correctly."""
        result = client_with_fixtures.get("/api/conversations/v0test123")
        assert result is not None
        assert isinstance(result, dict)
        assert result["conversation_id"] == "v0test123"
        assert result["conversation_version"] == "V0"

    def test_fixture_404(self, client_with_fixtures: APIClient):
        """Test that 404 fixtures return None."""
        result = client_with_fixtures.get("/api/conversations/notfound")
        assert result is None

    def test_fixture_with_query_params(self, client_with_fixtures: APIClient):
        """Test that fixtures with query params work."""
        result = client_with_fixtures.get(
            "/api/conversations/v0test123/events?limit=100&reverse=true"
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "events" in result
        assert len(result["events"]) == 2


class TestAPIClientLogging:
    """Test APIClient logging functionality."""

    def test_logging_creates_files(
        self, client_with_logging: APIClient, fixtures_dir: Path
    ):
        """Test that logging creates request/response files."""
        # Configure fixture dir to avoid real API calls
        client_with_logging.fixture_dir = fixtures_dir

        # Make a request
        result = client_with_logging.get("/api/conversations/v0test123")
        assert result is not None

        # Check log files were created
        log_dir = client_with_logging.log_dir
        assert log_dir is not None
        assert log_dir.exists()

        request_file = log_dir / "0001-request.json"
        response_file = log_dir / "0001-response.json"

        assert request_file.exists()
        assert response_file.exists()

        # Verify request log content
        with open(request_file) as f:
            request_data = json.load(f)
        assert request_data["method"] == "GET"
        assert "v0test123" in request_data["url"]
        # Auth header should not be logged
        assert "Authorization" not in request_data["headers"]

        # Verify response log content
        with open(response_file) as f:
            response_data = json.load(f)
        assert response_data["status_code"] == 200
        assert response_data["body"]["conversation_id"] == "v0test123"

    def test_call_counter_increments(
        self, client_with_logging: APIClient, fixtures_dir: Path
    ):
        """Test that the call counter increments properly."""
        client_with_logging.fixture_dir = fixtures_dir

        client_with_logging.get("/api/conversations/v0test123")
        client_with_logging.get("/api/conversations/v1test456")

        log_dir = client_with_logging.log_dir
        assert log_dir is not None
        assert (log_dir / "0001-request.json").exists()
        assert (log_dir / "0002-request.json").exists()


class TestAPIClientErrors:
    """Test APIClient error handling."""

    def test_network_error(self):
        """Test that network errors raise APIError."""
        client = APIClient(
            base_url="https://example.com",
            api_key="test-key",
        )

        from urllib.error import URLError

        with patch.object(client, "_try_fixture", return_value=None):
            with patch("oh_api.client.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = URLError("Connection refused")
                with pytest.raises(APIError) as exc_info:
                    client.get("/api/test")
                assert "Network error" in str(exc_info.value)

    def test_http_error_non_404(self):
        """Test that non-404 HTTP errors raise APIError."""
        client = APIClient(
            base_url="https://example.com",
            api_key="test-key",
        )

        from email.message import Message
        from urllib.error import HTTPError

        headers = Message()
        with patch.object(client, "_try_fixture", return_value=None):
            with patch("oh_api.client.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = HTTPError(
                    "https://example.com", 500, "Internal Server Error", headers, None
                )
                with pytest.raises(APIError) as exc_info:
                    client.get("/api/test")
                assert exc_info.value.status_code == 500
