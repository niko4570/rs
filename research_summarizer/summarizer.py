"""Summarizer that produces a final summary from collected evidence."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from research_summarizer.models import StepResult
from research_summarizer.prompts import SUMMARIZE_SYSTEM_PROMPT


def summarize_evidence(request: str, evidence: list[StepResult], model: ChatOpenAI) -> str:
    """Produce a final summary from collected evidence.

    Args:
        request: The original user request.
        evidence: Results from executed research steps.
        model: A ChatOpenAI instance.

    Returns:
        Raw summary text (to be fed to the parser).
    """
    evidence_text = "\n\n---\n\n".join(
        f"Source ({r.step.action}: {r.step.input}):\n{r.content}"
        for r in evidence
    )

    messages = [
        SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}\n\nEvidence:\n{evidence_text}"),
    ]
    response = model.invoke(messages)
    return getattr(response, "content", str(response))
