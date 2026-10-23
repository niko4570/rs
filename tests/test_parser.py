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


def test_extract_skips_prose_brace_before_fenced_json():
    text = 'Note {see below}\n```json\n{"a": 1}\n```'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_skips_prose_brace_before_bare_json():
    text = 'First {a note} then {"a": 1}'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_skips_unclosed_prose_brace_before_json():
    text = 'Note {unclosed {"a": 1}'
    assert _extract_json(text) == '{"a": 1}'


def test_extract_does_not_salvage_nested_object_after_prose():
    with pytest.raises(ParseError, match="Could not extract JSON"):
        _extract_json('Comment {"broken": , "nested": {"a": 1}}')


def test_extract_still_rejects_two_objects_separated_by_prose_braces():
    with pytest.raises(ParseError, match="multiple objects"):
        _extract_json('Note {x} {"a": 1} then {"b": 2}')


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

    def test_accepts_only_evidence_url_when_allowlist_supplied(self):
        result = parse_summary(_VALID_JSON, allowed_urls={"https://example.com"})
        assert result.sources[0].url == "https://example.com"

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
    def test_rejects_url_absent_from_evidence(self):
        with pytest.raises(ParseError, match="Source validation failed"):
            parse_summary(_VALID_JSON, allowed_urls={"https://other.example"})

    def test_rejects_source_when_evidence_has_no_urls(self):
        with pytest.raises(ParseError, match="Source validation failed"):
            parse_summary(_VALID_JSON, allowed_urls=set())


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


def _cited_result(url: str | None = "https://example.com", excerpt: str = "relevant text"):
    data = json.loads(_VALID_JSON)
    data["sources"] = [{"title": "Example", "url": url}] if url else []
    data["citations"] = [
        {"bullet_index": index, "source_url": url, "excerpt": excerpt}
        for index in range(4)
    ]
    return data


def test_validates_each_bullet_against_its_source_content():
    data = _cited_result()
    result = parse_summary(
        json.dumps(data),
        allowed_urls={"https://example.com"},
        citation_evidence={"https://example.com": "Some relevant  text appears here."},
    )
    assert len(result.citations) == 4


def test_rejects_missing_bullet_citation_when_evidence_exists():
    data = _cited_result()
    data["citations"] = data["citations"][:3]
    with pytest.raises(ParseError, match="every bullet needs a citation"):
        parse_summary(json.dumps(data), citation_evidence={"https://example.com": "relevant text"})


@pytest.mark.parametrize("include_citations", [False, True])
def test_off_topic_source_requires_citations_even_when_answer_is_unavailable(include_citations):
    content = "Solace is a music festival. It takes place in June."
    data = _cited_result(excerpt="Solace is a music festival.")
    data["summary_bullets"] = [
        "The source describes a music festival, not a battery.",
        "The supplied festival description cannot establish battery cycle life.",
        "No battery cycle count can be inferred from this source.",
        "The request cannot be answered from the supplied festival content.",
    ]
    data["caveats"] = ["No relevant battery evidence was supplied."]
    evidence = {"https://example.com": content}
    if not include_citations:
        data["citations"] = []
        with pytest.raises(ParseError, match="every bullet needs a citation"):
            parse_summary(json.dumps(data), citation_evidence=evidence)
    else:
        result = parse_summary(json.dumps(data), citation_evidence=evidence)
        assert len(result.citations) == 4
        assert result.summary_bullets == data["summary_bullets"]


def test_rejects_excerpt_from_a_different_source():
    data = _cited_result(excerpt="only in other source")
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_summary(json.dumps(data), citation_evidence={"https://example.com": "relevant text"})


def test_accepts_excerpt_that_renders_a_markdown_link():
    data = _cited_result(excerpt="See official guidance for details.")
    result = parse_summary(
        json.dumps(data),
        citation_evidence={
            "https://example.com": "The rule applies. See [official guidance](https://x/g) for details."
        },
    )
    assert result.citations[0].excerpt == "See official guidance for details."


def test_accepts_excerpt_that_drops_emphasis_markers():
    data = _cited_result(excerpt="US Regulations: The rule mandates audits.")
    result = parse_summary(
        json.dumps(data),
        citation_evidence={
            "https://example.com": "**US Regulations**: The rule mandates audits."
        },
    )
    assert result.citations[0].excerpt.startswith("US Regulations")


def test_accepts_excerpt_with_underscore_emphasis_rendered():
    data = _cited_result(excerpt="This is italic and bold text.")
    parse_summary(
        json.dumps(data),
        citation_evidence={"https://example.com": "This is _italic_ and __bold__ text."},
    )


def test_markdown_normalization_does_not_accept_fabricated_text():
    data = _cited_result(excerpt="Official guidance is optional")
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_summary(
            json.dumps(data),
            citation_evidence={"https://example.com": "[Official guidance](https://x/g) applies."},
        )


@pytest.mark.parametrize("excerpt", ["[]()", "![]()", "   "])
def test_rejects_excerpt_that_normalizes_to_empty(excerpt):
    data = _cited_result(excerpt=excerpt)
    with pytest.raises(ParseError, match="empty after Markdown normalization"):
        parse_summary(
            json.dumps(data),
            citation_evidence={"https://example.com": "real evidence text"},
        )


def test_rejects_excerpt_that_is_only_emphasis_markers():
    data = _cited_result(excerpt="**")
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_summary(
            json.dumps(data),
            citation_evidence={"https://example.com": "real evidence text"},
        )


def test_rejects_excerpt_created_by_stripping_a_literal_marker():
    data = _cited_result(excerpt="53")
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_summary(
            json.dumps(data),
            citation_evidence={"https://example.com": "the value 5*3 appears"},
        )


def test_accepts_excerpt_that_keeps_a_literal_marker():
    data = _cited_result(excerpt="5*3")
    result = parse_summary(
        json.dumps(data),
        citation_evidence={"https://example.com": "the value 5*3 appears"},
    )
    assert result.citations[0].excerpt == "5*3"


def test_rejects_excerpt_created_by_mixed_emphasis_and_literal_marker():
    data = _cited_result(excerpt="53")
    with pytest.raises(ParseError, match="excerpt is absent"):
        parse_summary(
            json.dumps(data),
            citation_evidence={"https://example.com": "the value **5*3** appears"},
        )


def test_accepts_excerpt_that_drops_code_markers():
    data = _cited_result(excerpt="Run the command now.")
    result = parse_summary(
        json.dumps(data),
        citation_evidence={"https://example.com": "Run `the command` now."},
    )
    assert result.citations[0].excerpt == "Run the command now."


def test_rejects_citation_to_source_not_listed_in_result():
    data = _cited_result()
    data["sources"] = []
    with pytest.raises(ParseError, match="absent from sources"):
        parse_summary(json.dumps(data), citation_evidence={"https://example.com": "relevant text"})


def test_rejects_citation_with_invalid_bullet_index():
    data = _cited_result()
    data["citations"][0]["bullet_index"] = 4
    with pytest.raises(ParseError, match="bullet index is out of range"):
        parse_summary(json.dumps(data), citation_evidence={"https://example.com": "relevant text"})


def test_local_file_citations_have_no_web_url():
    data = _cited_result(url=None, excerpt="Research notes")
    result = parse_summary(json.dumps(data), citation_evidence={None: "Research notes here."})
    assert all(citation.source_url is None for citation in result.citations)


def test_no_evidence_requires_no_citations():
    data = _cited_result()
    with pytest.raises(ParseError, match="source is absent"):
        parse_summary(json.dumps(data), citation_evidence={})


@pytest.mark.parametrize("wrap", [
    lambda a, b: a + "\n" + b,
    lambda a, b: f"```json\n{a}\n```\n```json\n{b}\n```",
    lambda a, b: f"Here is the result: {a}\nRevision: {b}",
])
def test_rejects_multiple_objects_in_all_wrappers(wrap):
    with pytest.raises(ParseError, match="multiple objects"):
        parse_summary(wrap(_VALID_JSON, _VALID_JSON))


def test_rejects_fields_split_across_objects_like_live_response():
    data = json.loads(_VALID_JSON)
    bullets = {"summary_bullets": data.pop("summary_bullets")}
    with pytest.raises(ParseError, match="multiple objects"):
        parse_summary(json.dumps(bullets) + "\n" + json.dumps(data))


def test_nested_objects_and_braces_inside_strings_are_one_object():
    data = json.loads(_VALID_JSON)
    data["key_details"] = 'A literal {brace} and an escaped "quote".'
    result = parse_summary(f"```json\n{json.dumps(data)}\n```")
    assert result.key_details == data["key_details"]


def test_does_not_salvage_nested_object_from_malformed_outer_json():
    with pytest.raises(ParseError, match="Malformed JSON"):
        parse_summary('{"broken": , "nested": ' + _VALID_JSON + '}')


def test_rejects_trailing_garbage_after_direct_json():
    with pytest.raises(ParseError, match="trailing content"):
        parse_summary(_VALID_JSON + " garbage")
