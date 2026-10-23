"""Source metadata is owned by Python; model IDs cannot create or reattribute URLs."""

import json

import pytest

from research_summarizer.evidence import format_synthesis_evidence
from research_summarizer.models import SourceContent
from research_summarizer.parser import ParseError, parse_synthesis


def draft(source_id="S1", excerpt="Original text"):
    return {
        "summary_bullets": ["Point"] * 4,
        "key_details": "Details",
        "caveats": [],
        "citations": [
            {"bullet_index": i, "source_id": source_id, "excerpt": excerpt}
            for i in range(4)
        ],
    }


@pytest.fixture
def sources():
    return {
        "S1": SourceContent(title="Actual title", url="https://example.com/category",
                            content="**Original text** from the acquired page."),
        "S2": SourceContent(title="Second title", url="https://example.com/second",
                            content="Other evidence"),
    }


def test_restores_exact_acquired_metadata_and_only_cited_sources(sources):
    result = parse_synthesis(json.dumps(draft()), sources)
    assert [s.model_dump() for s in result.sources] == [
        {"title": "Actual title", "url": "https://example.com/category", "snippet_used": None}
    ]
    assert len(result.citations) == 4
    assert all(c.source_url == "https://example.com/category" for c in result.citations)
    assert all(c.excerpt == "Original text" for c in result.citations)
    assert "source_id" not in result.model_dump_json()


@pytest.mark.parametrize("source_id", ["S3", "s1", "S1-S2", "https://example.com/new", ""])
def test_rejects_unknown_or_modified_source_ids(sources, source_id):
    with pytest.raises(ParseError, match="unknown source ID"):
        parse_synthesis(json.dumps(draft(source_id)), sources)


@pytest.mark.parametrize("field,value", [
    ("sources", [{"title": "Invented", "url": "https://example.com/new"}]),
    ("url", "https://example.com/new"),
])
def test_rejects_model_supplied_source_metadata(sources, field, value):
    payload = draft()
    payload[field] = value
    with pytest.raises(ParseError, match="Extra inputs"):
        parse_synthesis(json.dumps(payload), sources)


def test_rejects_url_in_citation_even_with_valid_id(sources):
    payload = draft()
    payload["citations"][0]["source_url"] = "https://example.com/new"
    with pytest.raises(ParseError, match="Extra inputs"):
        parse_synthesis(json.dumps(payload), sources)


def test_valid_id_cannot_borrow_excerpt_from_another_source(sources):
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_synthesis(json.dumps(draft("S2")), sources)


def test_duplicate_url_does_not_allow_wrong_id_excerpt(sources):
    sources["S2"].url = sources["S1"].url
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_synthesis(json.dumps(draft("S2")), sources)
    payload = draft()
    payload["citations"][1].update(source_id="S2", excerpt="Other evidence")
    result = parse_synthesis(json.dumps(payload), sources)
    assert len(result.sources) == 1
    assert result.citations[1].excerpt == "Other evidence"


def test_local_file_id_resolves_to_null_url():
    result = parse_synthesis(json.dumps(draft()), {"S1": SourceContent(content="Original text")})
    assert result.sources == []
    assert all(c.source_url is None for c in result.citations)


def test_empty_acquisition_has_no_valid_ids():
    with pytest.raises(ParseError, match="unknown source ID"):
        parse_synthesis(json.dumps(draft()), {})
    payload = draft()
    payload["citations"] = []
    assert parse_synthesis(json.dumps(payload), {}).sources == []


@pytest.mark.parametrize("change,message", [
    (lambda p: p["citations"].pop(), "every bullet"),
    (lambda p: p["citations"][0].update(bullet_index=4), "out of range"),
    (lambda p: p["citations"][0].update(excerpt="x" * 501), "at most 500"),
    (lambda p: p["citations"][0].update(excerpt="![](image)"), "empty after Markdown"),
])
def test_keeps_existing_citation_guards(sources, change, message):
    payload = draft()
    change(payload)
    with pytest.raises(ParseError, match=message):
        parse_synthesis(json.dumps(payload), sources)


def test_rejects_multiple_json_objects(sources):
    raw = json.dumps(draft())
    with pytest.raises(ParseError, match="multiple objects"):
        parse_synthesis(f"```json\n{raw}\n```\n```json\n{raw}\n```", sources)


def test_formats_exact_registry_ids_and_keeps_source_text(sources):
    text = format_synthesis_evidence(sources)
    assert "Source ID: S1\nTitle: Actual title\nURL: https://example.com/category" in text
    assert "Source ID: S2" in text
    assert "**Original text** from the acquired page." in text
    assert format_synthesis_evidence({}, "Fetch failed") == "Fetch failed"
