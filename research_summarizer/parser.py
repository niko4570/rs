"""Parser that converts raw LLM text into a typed SummaryResult.

Strategy (conservative, DeepSeek-compatible):
1. Take the raw final answer text.
2. Ask the model to convert it to JSON matching SummaryResult schema.
3. Validate with Pydantic.

No retry yet — that comes in Phase 1c.
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from research_summarizer.models import SummaryResult

logger = logging.getLogger(__name__)

_PARSE_SYSTEM_PROMPT = """Convert the following research summary into a JSON object matching this schema:

{
  "summary_bullets": ["bullet 1", "bullet 2", ...],  // 4-7 bullets
  "key_details": "facts, dates, names, numbers, tradeoffs",
  "sources": [
    {"title": "Page Title", "url": "https://...", "snippet_used": "optional specific text"}
  ],
  "caveats": ["specific caveat 1", "specific caveat 2"]
}

Rules:
- summary_bullets must have exactly 4-7 items.
- sources must only include sources that were actually used in the summary.
- caveats must be specific, not generic phrases like "may be incomplete."
- Return ONLY the JSON object, no other text."""


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


def parse_summary(raw_answer: str, model: ChatOpenAI) -> SummaryResult:
    """Parse a raw research summary into a typed SummaryResult.

    Uses a second LLM call to convert free-text into structured JSON.
    This is the conservative path — it works with any OpenAI-compatible
    provider, including DeepSeek.

    Args:
        raw_answer: The final text output from the agent.
        model: A ChatOpenAI instance to use for parsing.

    Returns:
        A validated SummaryResult.

    Raises:
        ParseError: If parsing or validation fails.
    """
    messages = [
        SystemMessage(content=_PARSE_SYSTEM_PROMPT),
        HumanMessage(content=raw_answer),
    ]

    try:
        response = model.invoke(messages)
    except Exception as exc:
        raise ParseError(f"Model call for parsing failed: {exc}", raw_text=raw_answer) from exc

    content = getattr(response, "content", str(response))

    try:
        json_text = _extract_json(content)
        logger.debug("Extracted JSON for parsing: %s", json_text[:200])
        data = json.loads(json_text)
    except (ParseError, json.JSONDecodeError) as exc:
        raise ParseError(f"JSON extraction failed: {exc}", raw_text=content) from exc

    try:
        result = SummaryResult.model_validate(data)
    except ValidationError as exc:
        raise ParseError(
            f"Validation failed: {exc}",
            raw_text=json_text,
        ) from exc

    return result
