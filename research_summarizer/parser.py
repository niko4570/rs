"""Parser that converts raw LLM text into a typed SummaryResult.

Strategy (conservative, DeepSeek-compatible):
1. Take the raw final answer text.
2. Ask the model to convert it to JSON matching SummaryResult schema.
3. Validate with Pydantic.
4. If it fails, retry once with the specific error as feedback.
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


def _build_retry_prompt(original_answer: str, error_message: str) -> str:
    """Build a retry prompt that includes the specific error to fix."""
    return (
        f"Your previous JSON conversion had errors. Fix them and return ONLY the corrected JSON.\n\n"
        f"Errors to fix:\n{error_message}\n\n"
        f"Original summary to convert:\n{original_answer}"
    )


def parse_summary_with_retry(
    raw_answer: str,
    model: ChatOpenAI,
    max_attempts: int = 2,
) -> SummaryResult:
    """Parse a raw summary with one retry on failure.

    First attempt: normal parsing.
    If that fails: retry once with the specific error as feedback,
    so the model can fix structural issues without re-running research.

    Args:
        raw_answer: The final text output from the agent.
        model: A ChatOpenAI instance to use for parsing.
        max_attempts: Maximum number of parse attempts (default 2).

    Returns:
        A validated SummaryResult.

    Raises:
        ParseError: If all attempts fail.
    """
    last_error: ParseError | None = None

    for attempt in range(max_attempts):
        try:
            if attempt == 0:
                return parse_summary(raw_answer, model)
            else:
                # Retry with failure feedback
                retry_prompt = _build_retry_prompt(
                    raw_answer, str(last_error)
                )
                return parse_summary(retry_prompt, model)
        except ParseError as exc:
            last_error = exc
            logger.debug("Parse attempt %d failed: %s", attempt + 1, exc)

    # All attempts exhausted — re-raise the last error
    raise last_error  # type: ignore[misc]
