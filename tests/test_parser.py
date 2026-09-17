"""Tests for structured output parsing (JSON extraction + Pydantic validation)."""

import json

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


class TestParseSummaryValid:
    def test_parses_valid_json(self):
        result = parse_summary(_VALID_JSON)
        assert len(result.summary_bullets) == 4
        assert result.key_details == "Some key facts and figures."
        assert len(result.sources) == 1
        assert result.sources[0].url == "https://example.com"
        assert result.sources[0].title == "Example Source"

    def test_parses_inside_markdown_block(self):
        result = parse_summary(f"```json\n{_VALID_JSON}\n```")
        assert len(result.summary_bullets) == 4

    def test_parses_with_minimum_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific reason"],
        }
        result = parse_summary(json.dumps(data))
        assert len(result.summary_bullets) == 4

    def test_parses_with_maximum_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d", "e", "f", "g"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        result = parse_summary(json.dumps(data))
        assert len(result.summary_bullets) == 7

    def test_source_without_title_is_ok(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [{"url": "https://x.com"}],
            "caveats": ["specific"],
        }
        result = parse_summary(json.dumps(data))
        assert result.sources[0].title is None
        assert result.sources[0].url == "https://x.com"


class TestParseSummaryRejects:
    def test_rejects_too_few_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary(json.dumps(data))

    def test_rejects_too_many_bullets(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "key_details": "ok",
            "sources": [],
            "caveats": ["specific"],
        }
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary(json.dumps(data))

    def test_rejects_missing_url_in_source(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [{"title": "No URL"}],
            "caveats": ["specific"],
        }
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary(json.dumps(data))

    def test_rejects_missing_key_details(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "sources": [],
            "caveats": ["specific"],
        }
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary(json.dumps(data))

    def test_rejects_missing_caveats(self):
        data = {
            "summary_bullets": ["a", "b", "c", "d"],
            "key_details": "ok",
            "sources": [],
        }
        with pytest.raises(ParseError, match="Validation failed"):
            parse_summary(json.dumps(data))

    def test_rejects_non_json_response(self):
        with pytest.raises(ParseError, match="JSON extraction failed"):
            parse_summary("Just a regular text response, not JSON at all.")
