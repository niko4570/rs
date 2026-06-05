"""Tests for Phase 1a: Structured output parsing."""

import json
from unittest.mock import Mock

import pytest

from research_summarizer.parser import ParseError, _extract_json, parse_summary


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_direct_json():
    text = '{"summary_bullets": ["a", "b", "c", "d"], "key_details": "x", "sources": [], "caveats": ["y"]}'
    result = _extract_json(text)
    assert result == text


def test_extract_from_markdown_code_block():
    text = 'Here is the output:\n```json\n{"summary_bullets": ["a", "b", "c", "d"], "key_details": "x", "sources": [], "caveats": ["y"]}\n```\nDone.'
    result = _extract_json(text)
    data = json.loads(result)
    assert data["summary_bullets"] == ["a", "b", "c", "d"]


def test_extract_bare_json_in_text():
    text = 'Some preamble {"summary_bullets": ["a", "b", "c", "d"], "key_details": "x", "sources": [], "caveats": ["y"]} some suffix'
    result = _extract_json(text)
    data = json.loads(result)
    assert data["key_details"] == "x"


def test_extract_no_json_raises():
    with pytest.raises(ParseError, match="Could not extract JSON"):
        _extract_json("Just some regular text, no JSON here.")


# ---------------------------------------------------------------------------
# parse_summary
# ---------------------------------------------------------------------------


_VALID_JSON = """{
    "summary_bullets": ["Point one", "Point two", "Point three", "Point four"],
    "key_details": "Some key facts and figures.",
    "sources": [
        {"title": "Example Source", "url": "https://example.com", "snippet_used": "relevant text"}
    ],
    "caveats": ["Source may have bias toward industry"]
}"""


def _mock_model(content: str):
    """Create a mock ChatOpenAI that returns the given content."""
    model = Mock()
    response = Mock()
    response.content = content
    model.invoke.return_value = response
    return model


class TestParseSummaryValid:
    """Tests for successful parsing."""

    def test_parses_valid_json(self):
        model = _mock_model(_VALID_JSON)
        result = parse_summary("some raw answer text", model)
        assert len(result.summary_bullets) == 4
        assert result.key_details == "Some key facts and figures."
        assert len(result.sources) == 1
        assert result.sources[0].url == "https://example.com"
        assert result.sources[0].title == "Example Source"

    def test_parses_inside_markdown_block(self):
        model = _mock_model(f"```json\n{_VALID_JSON}\n```")
        result = parse_summary("answer text", model)
        assert len(result.summary_bullets) == 4

    def test_parses_with_minimum_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific reason"],
        }
        model = _mock_model(json.dumps(data))
        result = parse_summary("raw", model)
        assert len(result.summary_bullets) == 4

    def test_parses_with_maximum_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d", "e", "f", "g"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        result = parse_summary("raw", model)
        assert len(result.summary_bullets) == 7

    def test_source_without_title_is_ok(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [{"url": "https://x.com"}],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        result = parse_summary("raw", model)
        assert result.sources[0].title is None
        assert result.sources[0].url == "https://x.com"


class TestParseSummaryRejects:
    """Tests for rejection of invalid output."""

    def test_rejects_too_few_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary("raw", model)

    def test_rejects_too_many_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary("raw", model)

    def test_rejects_missing_url_in_source(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [{"title": "No URL"}],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary("raw", model)

    def test_rejects_missing_key_details(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "sources": [],
            "caveats": ["specific"],
        }
        model = _mock_model(json.dumps(data))
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary("raw", model)

    def test_rejects_missing_caveats(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [],
        }
        model = _mock_model(json.dumps(data))
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary("raw", model)

    def test_rejects_non_json_response(self):
        model = _mock_model("Just a regular text response, not JSON at all.")
        with pytest.raises(ParseError, match="JSON extraction failed"):
            parse_summary("raw", model)

    def test_rejects_model_call_failure(self):
        model = Mock()
        model.invoke.side_effect = RuntimeError("API connection lost")
        with pytest.raises(ParseError, match="Model call for parsing failed"):
            parse_summary("raw", model)
