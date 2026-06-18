"""Tests for Phase 3: critique and revision of summaries."""

import json
from unittest.mock import Mock

import pytest

from research_summarizer.critique import critique_output, revise_output
from research_summarizer.models import CritiqueResult, ResearchStep, StepResult, SummaryResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary(url: str = "https://x.com") -> SummaryResult:
    return SummaryResult(
        summary_bullets=["Point 1", "Point 2", "Point 3", "Point 4"],
        key_details="Some facts.",
        sources=[{"title": "Source", "url": url}],
        caveats=["Limited to one source"],
    )


def _evidence() -> list[StepResult]:
    return [
        StepResult(
            step=ResearchStep(action="fetch", input="https://x.com", purpose="test"),
            content="Title: T\nURL: https://x.com\nText: content",
        ),
    ]


# ---------------------------------------------------------------------------
# Critique tests
# ---------------------------------------------------------------------------


class TestCritique:
    """Tests for critique_output — evaluates summary quality."""

    def test_parses_valid_critique_json(self):
        model = Mock()
        model.invoke.return_value = Mock(content=json.dumps({
            "source_fidelity": 0.85,
            "source_diversity": 0.70,
            "caveat_specificity": 0.60,
            "completeness": 0.90,
            "overall_score": 0.76,
            "gaps": ["Missing regional data"],
            "should_revise": True,
        }))

        result = critique_output(_summary(), _evidence(), model)
        assert result.overall_score == 0.76
        assert result.should_revise is True
        assert len(result.gaps) == 1

    def test_fallback_on_invalid_json(self):
        model = Mock()
        model.invoke.return_value = Mock(content="not json at all")

        result = critique_output(_summary(), _evidence(), model)
        assert result.overall_score == 0.5
        assert result.should_revise is True
        assert any("parsing failed" in g for g in result.gaps)

    def test_high_score_no_revision_needed(self):
        model = Mock()
        model.invoke.return_value = Mock(content=json.dumps({
            "source_fidelity": 0.95,
            "source_diversity": 0.95,
            "caveat_specificity": 0.95,
            "completeness": 0.95,
            "overall_score": 0.95,
            "gaps": [],
            "should_revise": False,
        }))

        result = critique_output(_summary(), _evidence(), model)
        assert result.overall_score == 0.95
        assert result.should_revise is False


# ---------------------------------------------------------------------------
# Revision tests
# ---------------------------------------------------------------------------


class TestRevision:
    """Tests for revise_output — generates improved summary draft."""

    def test_revision_prompt_contains_gaps(self):
        model = Mock()
        model.invoke.return_value = Mock(content="revised draft")

        critique = CritiqueResult(
            source_fidelity=0.6,
            source_diversity=0.7,
            caveat_specificity=0.5,
            completeness=0.8,
            overall_score=0.65,
            gaps=["Add more sources", "Be specific about dates"],
            should_revise=True,
        )

        result = revise_output(_summary(), critique, _evidence(), model)
        assert result == "revised draft"

        # Verify the prompt contains the gaps
        call_args = model.invoke.call_args
        messages = call_args[0][0]
        prompt_text = "\n".join(m.content for m in messages)
        assert "Add more sources" in prompt_text
        assert "source_fidelity (currently 0.6)" in prompt_text

