"""Parser that converts raw LLM JSON output into a typed SummaryResult.

This is a pure JSON-extraction + Pydantic validation step — no LLM calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping

from pydantic import ValidationError

from research_summarizer.models import SummaryResult


class ParseError(Exception):
    """Raised when the parser cannot produce a valid SummaryResult."""

    def __init__(self, message: str, raw_text: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text


# Inline Markdown reduced to the visible text it renders to. The synthesizer may
# return either the raw Markdown (``[text](url)``, ``**text**``) or its rendered
# text, so citation matching must accept both: the visible wording is what the
# excerpt actually asserts. The same normalization is applied to the excerpt and
# to the evidence, so the excerpt must still occur contiguously in the source.
#
# Only *paired* emphasis and code markers are removed. Stripping every ``*`` and
# backtick globally would collapse distinct strings (an excerpt ``"53"`` would
# match evidence ``"the value 5*3 appears"``), so a literal marker in otherwise
# plain text is preserved and only matching opening/closing pairs are dropped.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_UNDERSCORE_RE = re.compile(r"(?<![\w])_{1,2}(?=\S)(.+?)(?<=\S)_{1,2}(?![\w])", re.DOTALL)
_MD_EMPHASIS_RE = re.compile(r"(?<!\*)(\*{1,3})(?=\S)([^*]+?)(?<=\S)\1(?!\*)", re.DOTALL)
_MD_CODE_RE = re.compile(r"(?<!`)(`{1,3})(?=\S)([^`]+?)(?<=\S)\1(?!`)", re.DOTALL)


def _normalize_markdown(text: str) -> str:
    """Reduce inline Markdown markup to the visible text it renders to."""
    text = _MD_IMAGE_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_UNDERSCORE_RE.sub(r"\1", text)
    text = _MD_EMPHASIS_RE.sub(r"\2", text)
    return _MD_CODE_RE.sub(r"\2", text)


def _matching_brace_end(text: str, start: int) -> int | None:
    """Return the index of the ``}`` matching the ``{`` at ``start``, or ``None``."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _extract_json(text: str) -> str:
    """Extract exactly one JSON object from text that may contain commentary.

    Braces inside prose are skipped so commentary like ``{see below}`` does not hide
    a later object. A malformed object at the very start of the response is still
    reported as malformed rather than mined for a nested object, and the whole
    braced region is skipped on failure so a nested object is never salvaged.
    """
    text = text.strip()
    decoder = json.JSONDecoder()
    objects: list[str] = []
    position = 0
    while position < len(text):
        start = text.find("{", position)
        if start < 0:
            break
        try:
            _, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            if start == 0:
                raise ParseError("Malformed JSON object in response.", raw_text=text)
            # Skip the brace-delimited region so nested braces are not salvaged;
            # an unclosed brace is treated as a lone prose brace.
            matched = _matching_brace_end(text, start)
            position = matched + 1 if matched is not None else start + 1
            continue
        objects.append(text[start:end])
        position = end
    if len(objects) > 1:
        raise ParseError("Expected exactly one JSON object; received multiple objects.", text)
    if not objects:
        raise ParseError("Could not extract JSON object from response.", raw_text=text)
    if text.startswith("{") and text[len(objects[0]):].strip():
        raise ParseError("Unexpected trailing content after JSON object.", text)
    return objects[0]


def parse_summary(
    raw_answer: str,
    allowed_urls: Collection[str] | None = None,
    citation_evidence: Mapping[str | None, str] | None = None,
) -> SummaryResult:
    """Extract and validate a SummaryResult from raw model output."""
    try:
        json_text = _extract_json(raw_answer)
        data = json.loads(json_text)
    except (ParseError, json.JSONDecodeError) as exc:
        raise ParseError(f"JSON extraction failed: {exc}", raw_text=raw_answer) from exc

    try:
        result = SummaryResult.model_validate(data)
    except ValidationError as exc:
        raise ParseError(f"Validation failed: {exc}", raw_text=json_text) from exc

    if allowed_urls is not None:
        unknown = {source.url for source in result.sources} - set(allowed_urls)
        if unknown:
            raise ParseError(
                "Source validation failed: response cited a URL absent from the evidence.",
                raw_text=json_text,
            )
    if citation_evidence is not None:
        _validate_citations(result, citation_evidence, json_text)
    return result


def _validate_citations(
    result: SummaryResult, evidence: Mapping[str | None, str], raw_text: str
) -> None:
    """Check coverage, source identity, and excerpt presence without another model call."""
    cited_bullets: set[int] = set()
    listed_urls = {source.url for source in result.sources}
    for citation in result.citations:
        if citation.bullet_index >= len(result.summary_bullets):
            raise ParseError("Citation validation failed: bullet index is out of range.", raw_text)
        if citation.source_url not in evidence:
            raise ParseError("Citation validation failed: source is absent from the evidence.", raw_text)
        if citation.source_url is not None and citation.source_url not in listed_urls:
            raise ParseError("Citation validation failed: source is absent from sources.", raw_text)
        excerpt = " ".join(_normalize_markdown(citation.excerpt).split())
        content = " ".join(_normalize_markdown(evidence[citation.source_url]).split())
        if not excerpt:
            raise ParseError(
                "Citation validation failed: excerpt is empty after Markdown normalization.",
                raw_text,
            )
        if excerpt not in content:
            raise ParseError("Citation validation failed: excerpt is absent from the source.", raw_text)
        cited_bullets.add(citation.bullet_index)

    if evidence and cited_bullets != set(range(len(result.summary_bullets))):
        raise ParseError("Citation validation failed: every bullet needs a citation.", raw_text)
