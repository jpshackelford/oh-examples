"""Pytest configuration and fixtures for testing oh_api."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Add the conversation-metrics directory to the path
PACKAGE_DIR = Path(__file__).parent.parent / "conversation-metrics"
sys.path.insert(0, str(PACKAGE_DIR))

# Import after path setup
from oh_api import APIClient  # noqa: E402


FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "https://app.all-hands.dev"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory path."""
    return FIXTURES_DIR


@pytest.fixture
def client_with_fixtures(fixtures_dir: Path) -> APIClient:
    """Create an APIClient that uses fixtures instead of real API."""
    return APIClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        fixture_dir=fixtures_dir,
    )


@pytest.fixture
def client_with_logging(tmp_path: Path) -> APIClient:
    """Create an APIClient with logging enabled."""
    return APIClient(
        base_url=BASE_URL,
        api_key="test-api-key",
        log_api_calls=True,
        log_dir=tmp_path / "api-logs",
    )
