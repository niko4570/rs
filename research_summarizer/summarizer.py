"""Synthesis layer: turns collected evidence into a structured SummaryResult."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from research_summarizer.models import SummaryResult
from research_summarizer.parser import parse_summary
from research_summarizer.prompts import SUMMARIZE_SYSTEM_PROMPT


def summarize_evidence(request: str, evidence: str, model: ChatOpenAI) -> SummaryResult:
    """Produce a structured summary from collected evidence in a single LLM call.

    The model is instructed to return JSON directly; the parser only extracts
    and validates it (no second LLM call).
    """
    messages = [
        SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}\n\nEvidence:\n{evidence}"),
    ]
    response = model.invoke(messages)
    raw_answer = getattr(response, "content", str(response))
    return parse_summary(raw_answer)
