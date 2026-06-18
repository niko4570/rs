"""Replanner that generates alternative steps when execution fails."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from research_summarizer.models import ResearchPlan, ResearchStep, RunState, StepResult
from research_summarizer.prompts import REPLAN_SYSTEM_PROMPT


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

    completed = sorted(state.read_files | state.fetched_urls | state.searched_urls)
    messages = [
        SystemMessage(content=REPLAN_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                "Failed step:\n"
                f"- action: {failed_step.action}\n"
                f"- input: {failed_step.input}\n"
                f"- purpose: {failed_step.purpose}\n"
                f"- error: {error_result.content[:500]}\n\n"
                "Completed step inputs:\n"
                f"{', '.join(completed) if completed else 'none yet'}\n\n"
                "Generate one replacement step or null."
            )
        ),
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
