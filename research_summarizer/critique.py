"""Critique module that evaluates summary quality against evidence.

Critique is a quality-improvement step, not a gate.
Validation (Phase 1b) is the deterministic gate.
Critique (Phase 3) finds gaps that validation cannot catch.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from research_summarizer.models import CritiqueResult, StepResult, SummaryResult
from research_summarizer.prompts import CRITIQUE_SYSTEM_PROMPT


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


def critique_output(
    summary: SummaryResult,
    evidence: list[StepResult],
    model: ChatOpenAI,
) -> CritiqueResult:
    """Evaluate a summary against its evidence.

    Args:
        summary: The parsed SummaryResult to evaluate.
        evidence: Collected evidence from research steps.
        model: A ChatOpenAI instance.

    Returns:
        A CritiqueResult with scores and improvement recommendations.
    """
    evidence_text = "\n\n---\n\n".join(
        f"Source ({r.step.action}: {r.step.input}):\n{r.content}"
        for r in evidence
        if not r.failed
    )

    summary_json = summary.model_dump_json()

    messages = [
        SystemMessage(content=CRITIQUE_SYSTEM_PROMPT),
        HumanMessage(content=f"Summary:\n{summary_json}\n\nEvidence:\n{evidence_text}"),
    ]
    response = model.invoke(messages)
    content = getattr(response, "content", str(response))

    try:
        json_text = _extract_json(content)
        data = json.loads(json_text)
        return CritiqueResult.model_validate(data)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        # Fallback: if critique fails, return a conservative result that suggests revision
        return CritiqueResult(
            source_fidelity=0.5,
            source_diversity=0.5,
            caveat_specificity=0.5,
            completeness=0.5,
            overall_score=0.5,
            gaps=[f"Critique parsing failed: {exc}"],
            should_revise=True,
        )


def revise_output(
    summary: SummaryResult,
    critique: CritiqueResult,
    evidence: list[StepResult],
    model: ChatOpenAI,
) -> str:
    """Generate a revised summary draft based on critique feedback.

    Args:
        summary: The current summary to revise.
        critique: CritiqueResult with specific improvement targets.
        evidence: Collected evidence to draw from.
        model: A ChatOpenAI instance.

    Returns:
        Revised raw summary text (to be fed to the parser).
    """
    from research_summarizer.summarizer import summarize_evidence

    gap_text = "\n".join(f"- {gap}" for gap in critique.gaps)
    revision_request = (
        f"Revise your summary to address these gaps:\n\n"
        f"{gap_text}\n\n"
        "Focus on improving:\n"
        f"- source_fidelity (currently {critique.source_fidelity:.1f})\n"
        f"- source_diversity (currently {critique.source_diversity:.1f})\n"
        f"- caveat_specificity (currently {critique.caveat_specificity:.1f})\n"
        f"- completeness (currently {critique.completeness:.1f})\n"
    )

    return summarize_evidence(revision_request, evidence, model)
