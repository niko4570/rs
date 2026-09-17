"""Parser that converts raw LLM JSON output into a typed SummaryResult.

This is a pure JSON-extraction + Pydantic validation step — no LLM calls.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from research_summarizer.models import SummaryResult


class ParseError(Exception):
    """Raised when the parser cannot produce a valid SummaryResult."""

    def __init__(self, message: str, raw_text: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text


def _extract_json(text: str) -> str:
    """Extract a JSON object from text that may contain surrounding commentary."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        return text

    # Try to find JSON inside markdown code blocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # Try to find any JSON object in the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)

    raise ParseError("Could not extract JSON object from response.", raw_text=text)


def parse_summary(raw_answer: str) -> SummaryResult:
    """Extract and validate a SummaryResult from raw model output."""
    try:
        json_text = _extract_json(raw_answer)
        data = json.loads(json_text)
    except (ParseError, json.JSONDecodeError) as exc:
        raise ParseError(f"JSON extraction failed: {exc}", raw_text=raw_answer) from exc

    try:
        return SummaryResult.model_validate(data)
    except ValidationError as exc:
        raise ParseError(f"Validation failed: {exc}", raw_text=json_text) from exc
