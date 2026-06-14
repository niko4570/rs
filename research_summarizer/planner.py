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

_PLAN_SYSTEM_PROMPT = """You are a research planner. Given a research request, produce a JSON plan with the steps needed to answer it.

Rules:
- If the request is a URL, plan: fetch that URL.
- If the request is a local file path (ends in .md, .txt, or looks like a path), plan: read that file.
- If the request is a topic/question, plan: 1-3 search queries, then fetch the most relevant results.
- Each step has: action ("search", "fetch", or "read_file"), input (the query/URL/path), and purpose (why this step).
- comparison_strategy: how you'll compare sources (e.g., "cross-check facts across 3 sources").

Return ONLY this JSON:
{
  "steps": [
    {"action": "search", "input": "search query", "purpose": "find recent articles"},
    {"action": "fetch", "input": "https://...", "purpose": "get full text"}
  ],
  "comparison_strategy": "cross-check key claims across sources"
}

Keep queries specific and actionable. For topic requests, use 1-3 search queries — don't pre-fetch URLs you don't know exist."""


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
        SystemMessage(content=_PLAN_SYSTEM_PROMPT),
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
