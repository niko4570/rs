"""Planner that generates research plans from user requests.

The LLM decides WHAT to do. The code enforces HOW it's done.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from research_summarizer.models import ResearchPlan, ResearchStep
from research_summarizer.prompts import PLAN_SYSTEM_PROMPT


def _extract_json(text: str) -> str:
    """Extract a JSON object from text."""
    text = text.strip()
    if text.startswith("{"):
        return text
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError("No JSON object found in response")


def plan_research(request: str, model: ChatOpenAI) -> ResearchPlan:
    """Generate a research plan for the given request.

    Uses an LLM to decide what steps are needed, returns a typed plan.

    Args:
        request: The user's research query, URL, or file path.
        model: A ChatOpenAI instance.

    Returns:
        A ResearchPlan with ordered steps.

    Raises:
        ValueError: If the LLM response cannot be parsed into a valid plan.
    """
    messages = [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=request),
    ]
    response = model.invoke(messages)
    content = getattr(response, "content", str(response))

    try:
        json_text = _extract_json(content)
        data = json.loads(json_text)
        plan = ResearchPlan.model_validate(data)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Failed to parse research plan: {exc}\nRaw: {content[:500]}") from exc

    if not plan.steps:
        raise ValueError(f"Plan has no steps. Raw: {content[:500]}")

    return plan
