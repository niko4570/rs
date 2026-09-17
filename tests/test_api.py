"""Tests for the FastAPI layer (thin adapter over run_agent).

``run_agent`` is mocked so these tests never call an LLM or the network.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from research_summarizer.api import app
from research_summarizer.models import Source, SummaryResult
from research_summarizer.parser import ParseError

client = TestClient(app)


def _summary() -> SummaryResult:
    return SummaryResult(
        summary_bullets=["Point 1", "Point 2", "Point 3", "Point 4"],
        key_details="Some key facts.",
        sources=[Source(title="Example", url="https://example.com/article")],
        caveats=["Limited to a single source"],
    )


@pytest.fixture
def mock_run_agent():
    with patch("research_summarizer.api.run_agent") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Valid requests
# ---------------------------------------------------------------------------


def test_valid_url_request(mock_run_agent):
    mock_run_agent.return_value = _summary()

    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com/article"},
    )

    assert response.status_code == 200
    mock_run_agent.assert_called_once_with("https://example.com/article")


def test_valid_file_request(mock_run_agent, tmp_path):
    mock_run_agent.return_value = _summary()
    uploads = tmp_path / ".uploads"
    with patch("research_summarizer.api._UPLOADS_DIR", uploads):
        response = client.post(
            "/api/research",
            data={"input_type": "file"},
            files={"file": ("notes.md", b"# Research notes\n", "text/markdown")},
        )

    assert response.status_code == 200

    request_arg = mock_run_agent.call_args.args[0]
    assert request_arg.startswith("Summarize the local file: .uploads/")
    assert request_arg.endswith(".md")

    saved = list(uploads.glob("*.md"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == "# Research notes\n"


# ---------------------------------------------------------------------------
# Missing / invalid input
# ---------------------------------------------------------------------------


def test_missing_input_type_returns_422():
    response = client.post("/api/research", data={})
    assert response.status_code == 422


def test_url_without_value(mock_run_agent):
    response = client.post("/api/research", data={"input_type": "url"})
    assert response.status_code == 400
    mock_run_agent.assert_not_called()


def test_invalid_url_scheme(mock_run_agent):
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "ftp://example.com/file"},
    )
    assert response.status_code == 400
    mock_run_agent.assert_not_called()


def test_invalid_url_no_scheme(mock_run_agent):
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "not a real url"},
    )
    assert response.status_code == 400
    mock_run_agent.assert_not_called()


def test_file_without_upload(mock_run_agent):
    response = client.post("/api/research", data={"input_type": "file"})
    assert response.status_code == 400
    mock_run_agent.assert_not_called()


def test_unsupported_file_type(mock_run_agent):
    response = client.post(
        "/api/research",
        data={"input_type": "file"},
        files={"file": ("document.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]
    mock_run_agent.assert_not_called()


def test_empty_file(mock_run_agent):
    response = client.post(
        "/api/research",
        data={"input_type": "file"},
        files={"file": ("empty.txt", b"   \n", "text/plain")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
    mock_run_agent.assert_not_called()


def test_unknown_input_type(mock_run_agent):
    response = client.post(
        "/api/research",
        data={"input_type": "topic", "url": "https://example.com"},
    )
    assert response.status_code == 400
    mock_run_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Agent / provider failures
# ---------------------------------------------------------------------------


def test_parse_error_returns_502(mock_run_agent):
    mock_run_agent.side_effect = ParseError("bad output", raw_text="raw")
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com"},
    )
    assert response.status_code == 502
    assert "valid structured result" in response.json()["detail"]


def test_missing_config_returns_503(mock_run_agent):
    mock_run_agent.side_effect = ValueError(
        "Missing API configuration. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL."
    )
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_planning_failure_returns_502(mock_run_agent):
    mock_run_agent.side_effect = ValueError("Plan produced no steps.")
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com"},
    )
    assert response.status_code == 502
    assert "planning failed" in response.json()["detail"]


def test_llm_provider_error_returns_502(mock_run_agent):
    import httpx
    from openai import APIError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    mock_run_agent.side_effect = APIError("boom", request, body={})
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com"},
    )
    assert response.status_code == 502
    assert "LLM provider error" in response.json()["detail"]


def test_unexpected_error_returns_500(mock_run_agent):
    mock_run_agent.side_effect = RuntimeError("something exploded")
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com"},
    )
    assert response.status_code == 500
    # Internal error text must not leak the exception message.
    assert "exploded" not in response.json()["detail"]


# ---------------------------------------------------------------------------
# Response serialization
# ---------------------------------------------------------------------------


def test_response_serialization(mock_run_agent):
    mock_run_agent.return_value = _summary()

    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com/article"},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"summary_bullets", "key_details", "sources", "caveats"}
    assert data["summary_bullets"] == ["Point 1", "Point 2", "Point 3", "Point 4"]
    assert data["key_details"] == "Some key facts."
    assert data["sources"] == [
        {
            "title": "Example",
            "url": "https://example.com/article",
            "snippet_used": None,
        }
    ]
    assert data["caveats"] == ["Limited to a single source"]


def test_response_serialization_is_valid_json(mock_run_agent):
    mock_run_agent.return_value = _summary()
    response = client.post(
        "/api/research",
        data={"input_type": "url", "url": "https://example.com/article"},
    )
    # Ensure the body is parseable JSON (serialization sanity check).
    json.loads(response.text)
