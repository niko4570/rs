"""Replanner that generates alternative steps when execution fails."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from research_summarizer.models import ResearchPlan, ResearchStep, RunState, StepResult

_REPLAN_PROMPT = """A research step failed. Generate ONE replacement step to recover.

Failed step:
  Action: {action}
  Input: {input}
  Purpose: {purpose}
  Error: {error}

Current plan status (steps done): {completed_steps}

Rules:
- If search returned no results, try a broader or different search query.
- If a URL is unavailable (paywall/403), search for the page title instead.
- If a page had no extractable content, try the next search result.
- If network failed, suggest a different URL or broader search.
- If you can't think of a reasonable alternative, return null.

Return ONLY this JSON:
{{"action": "search", "input": "new query or URL", "purpose": "why this alternative"}}

Or return: null"""


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("{"):
        return text
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError("No JSON found")


def replan_step(
    failed_step: ResearchStep,
    error_result: StepResult,
    plan: ResearchPlan,
    state: RunState,
    model: ChatOpenAI,
    replan_count: int,
    max_replans: int = 3,
) -> ResearchStep | None:
    """Generate an alternative step when one fails.

    Args:
        failed_step: The step that failed.
        error_result: The result with error details.
        plan: The current plan (for context).
        state: Current run state.
        model: ChatOpenAI instance.
        replan_count: How many replans have happened so far (across all steps).
        max_replans: Global cap on replans per run.

    Returns:
        A new ResearchStep, or None if replanning is exhausted or LLM returns null.
    """
    if replan_count >= max_replans:
        return None

    completed = [s.step.input for s in [error_result] if not s.failed]  # placeholder
    prompt = _REPLAN_PROMPT.format(
        action=failed_step.action,
        input=failed_step.input,
        purpose=failed_step.purpose,
        error=error_result.content[:500],
        completed_steps=", ".join(completed) if completed else "none yet",
    )

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="Generate a replacement step or null."),
    ]
    response = model.invoke(messages)
    content = getattr(response, "content", str(response)).strip()

    if content.lower().startswith("null") or content.strip() == "null":
        return None

    try:
        json_text = _extract_json(content)
        data = json.loads(json_text)
        return ResearchStep.model_validate(data)
    except (ValueError, json.JSONDecodeError, ValidationError):
        return None
