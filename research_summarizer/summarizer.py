"""Summarizer that produces a final summary from collected evidence."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from research_summarizer.models import StepResult

_SUMMARIZE_PROMPT = """You are a Research Summarizer Agent. Write a final summary from the evidence below.

Your job is to help users understand a topic from source material.

Workflow:
1. Compare sources instead of trusting the first result.
2. Separate facts from uncertainty.
3. Prefer concise summaries with citations.

Output format:
- Summary: 4-7 bullets
- Key details: facts, dates, names, numbers, and tradeoffs
- Sources: list source titles or URLs used
- Caveats: what may be missing, outdated, or uncertain

Do not invent citations. If sources are weak or unavailable, say so.
If a piece of evidence starts with [FETCH_ERROR], treat that source as unavailable — do not cite it or use its content."""


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
        SystemMessage(content=_SUMMARIZE_PROMPT),
        HumanMessage(content=f"Request: {request}\n\nEvidence:\n{evidence_text}"),
    ]
    response = model.invoke(messages)
    return getattr(response, "content", str(response))
