"""Shared pytest fixtures for research-summarizer-agent tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Tests must not emit traces to the real LangSmith project.
os.environ["LANGSMITH_TRACING"] = "false"


@pytest.fixture
def temp_project_root():
    """Temporary directory patched as PROJECT_ROOT."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch("research_summarizer.evidence.PROJECT_ROOT", root.resolve()):
            yield root


@pytest.fixture(autouse=True)
def clear_fetch_cache():
    """Clear the per-run fetch cache before every test."""
    from research_summarizer import evidence

    evidence._fetch_cache.clear()
    yield
    evidence._fetch_cache.clear()


@pytest.fixture
def mock_tavily_key():
    """Set TAVILY_API_KEY in environment for search_web tests."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
        yield


@pytest.fixture
def no_tavily_key():
    """Ensure TAVILY_API_KEY is absent."""
    with patch.dict("os.environ", {}, clear=True):
        yield
