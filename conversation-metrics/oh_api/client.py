"""Base HTTP client with request/response logging and fixture support."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class APIError(Exception):
    """Exception raised for API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class APIClient:
    """HTTP client for OpenHands API with logging and fixture support.

    Attributes:
        base_url: Base URL for the API (e.g., https://app.all-hands.dev)
        api_key: API key for authentication
        log_api_calls: If True, log all requests/responses to disk
        log_dir: Directory for API logs (default: .oh/api-logs)
        fixture_dir: If set, use fixtures from this directory instead of real API
    """

    base_url: str
    api_key: str
    log_api_calls: bool = False
    log_dir: Path | None = None
    fixture_dir: Path | None = None
    _call_counter: int = field(default=0, repr=False)

    def __post_init__(self):
        # Normalize base URL (remove trailing slash)
        self.base_url = self.base_url.rstrip("/")

        # Set default log directory
        if self.log_dir is None:
            self.log_dir = Path(".oh/api-logs")

        # Create log directory if logging is enabled
        if self.log_api_calls:
            self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Create log directory with timestamp subdirectory."""
        if self.log_dir is None:
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_dir = self.log_dir / timestamp
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _log_request(self, method: str, url: str, headers: dict[str, str]) -> None:
        """Log an API request to disk."""
        if not self.log_api_calls or self.log_dir is None:
            return

        request_data = {
            "method": method,
            "url": url,
            "headers": {k: v for k, v in headers.items() if k != "Authorization"},
            "timestamp": datetime.now().isoformat(),
        }

        filename = self.log_dir / f"{self._call_counter:04d}-request.json"
        with open(filename, "w") as f:
            json.dump(request_data, f, indent=2)

    def _log_response(
        self,
        status_code: int,
        body: Any,
        error: str | None = None,
    ) -> None:
        """Log an API response to disk."""
        if not self.log_api_calls or self.log_dir is None:
            return

        response_data = {
            "status_code": status_code,
            "body": body,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }

        filename = self.log_dir / f"{self._call_counter:04d}-response.json"
        with open(filename, "w") as f:
            json.dump(response_data, f, indent=2)

    def _get_fixture_key(self, method: str, url: str) -> str:
        """Generate a fixture key from method and URL."""
        # Remove base URL and normalize
        path = url.replace(self.base_url, "")
        # Replace special characters for filesystem
        safe_path = path.replace("/", "_").replace("?", "_q_").replace("&", "_a_")
        return f"{method}_{safe_path}"

    def _try_fixture(self, method: str, url: str) -> dict[str, Any] | None:
        """Try to load a response from fixtures."""
        if self.fixture_dir is None:
            return None

        fixture_key = self._get_fixture_key(method, url)
        fixture_file = self.fixture_dir / f"{fixture_key}.json"

        if fixture_file.exists():
            with open(fixture_file) as f:
                return json.load(f)
        return None

    def get(self, path: str) -> dict[str, Any] | list[Any] | None:
        """Make a GET request to the API.

        Args:
            path: API path (e.g., /api/conversations)

        Returns:
            Parsed JSON response, or None if 404

        Raises:
            APIError: For non-404 HTTP errors or network errors
        """
        url = f"{self.base_url}{path}"
        self._call_counter += 1

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        self._log_request("GET", url, headers)

        # Check for fixture first
        fixture_response = self._try_fixture("GET", url)
        if fixture_response is not None:
            status = fixture_response.get("status_code", 200)
            body = fixture_response.get("body")
            self._log_response(status, body)
            if status == 404:
                return None
            if status >= 400:
                raise APIError(f"HTTP {status}", status_code=status)
            return body

        # Make real request
        req = Request(url)
        for key, value in headers.items():
            req.add_header(key, value)

        try:
            with urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode())
                self._log_response(response.status, body)
                return body
        except HTTPError as e:
            error_body = None
            try:
                error_body = json.loads(e.read().decode())
            except Exception:
                pass

            self._log_response(e.code, error_body, error=str(e))

            if e.code == 404:
                return None
            raise APIError(f"HTTP {e.code}: {e.reason}", status_code=e.code) from e
        except URLError as e:
            self._log_response(0, None, error=str(e))
            raise APIError(f"Network error: {e.reason}") from e


def save_fixture(
    fixture_dir: Path,
    method: str,
    base_url: str,
    path: str,
    status_code: int,
    body: Any,
) -> Path:
    """Save a response as a fixture file.

    This helper is useful for recording real API responses for later testing.

    Args:
        fixture_dir: Directory to save fixtures
        method: HTTP method (GET, POST, etc.)
        base_url: Base URL of the API
        path: API path
        status_code: HTTP status code
        body: Response body

    Returns:
        Path to the saved fixture file
    """
    fixture_dir.mkdir(parents=True, exist_ok=True)

    # Generate fixture key
    url = f"{base_url}{path}"
    safe_path = path.replace("/", "_").replace("?", "_q_").replace("&", "_a_")
    fixture_key = f"{method}_{safe_path}"

    fixture_data = {
        "status_code": status_code,
        "body": body,
        "url": url,
        "method": method,
    }

    fixture_file = fixture_dir / f"{fixture_key}.json"
    with open(fixture_file, "w") as f:
        json.dump(fixture_data, f, indent=2)

    return fixture_file
