"""Tests for Phase 1b: validation of structured summaries."""

import pytest

from research_summarizer.models import (
    RunState,
    Source,
    SummaryResult,
    ValidationIssue,
)
from research_summarizer.validation import validate_summary


def _make_result(
    bullets=None,
    key_details="Some key details.",
    sources=None,
    caveats=None,
):
    return SummaryResult(
        summary_bullets=bullets if bullets is not None else ["a", "b", "c", "d"],
        key_details=key_details,
        sources=sources if sources is not None else [],
        caveats=caveats if caveats is not None else ["Data limited to one source"],
    )


class TestValidatePasses:
    """Tests where validation should pass (no errors)."""

    def test_all_sources_known(self):
        state = RunState(
            fetched_urls={"https://example.com/article"},
        )
        result = _make_result(
            sources=[Source(title="T", url="https://example.com/article")],
        )
        report = validate_summary(result, state)
        assert report.passed is True
        errors = [i for i in report.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_source_from_search_results(self):
        state = RunState(
            searched_urls={"https://news.site/story"},
        )
        result = _make_result(
            sources=[Source(url="https://news.site/story")],
        )
        report = validate_summary(result, state)
        assert report.passed is True

    def test_specific_caveats_pass(self):
        state = RunState()
        result = _make_result(
            caveats=["Source is an industry publication funded by Big Pharma"],
        )
        report = validate_summary(result, state)
        generic_issues = [i for i in report.issues if i.code == "generic_caveat"]
        assert len(generic_issues) == 0

    def test_no_state_still_validates_structure(self):
        """Validation shouldn't fail just because no state is tracked yet."""
        state = RunState()
        result = _make_result(
            sources=[Source(url="https://independent-source.com")],
        )
        report = validate_summary(result, state)
        # Source not in state → hallucinated_source error, so passed=False
        assert report.passed is False
        assert any(i.code == "hallucinated_source" for i in report.issues)


class TestValidateCatches:
    """Tests where validation should catch problems."""

    def test_hallucinated_source(self):
        state = RunState(
            fetched_urls={"https://real-source.com"},
        )
        result = _make_result(
            sources=[
                Source(url="https://real-source.com"),
                Source(url="https://made-up-fake-site.com"),
            ],
        )
        report = validate_summary(result, state)
        assert report.passed is False
        hallucinated = [i for i in report.issues if i.code == "hallucinated_source"]
        assert len(hallucinated) == 1
        assert "made-up-fake-site.com" in hallucinated[0].message
        assert hallucinated[0].severity == "error"

    def test_cited_failed_source(self):
        state = RunState(
            fetched_urls={"https://good.com"},
            failed_fetch_urls={"https://paywall.com/article"},
        )
        result = _make_result(
            sources=[
                Source(url="https://good.com"),
                Source(url="https://paywall.com/article"),
            ],
        )
        report = validate_summary(result, state)
        assert report.passed is False
        failed = [i for i in report.issues if i.code == "cited_failed_source"]
        assert len(failed) == 1
        assert "paywall.com" in failed[0].message

    def test_generic_caveat_rejected(self):
        state = RunState()
        result = _make_result(
            caveats=["Some specific limitation", "may be incomplete"],
        )
        report = validate_summary(result, state)
        generic = [i for i in report.issues if i.code == "generic_caveat"]
        assert len(generic) == 1
        assert "may be incomplete" in generic[0].message

    def test_multiple_generic_caveats_all_flagged(self):
        state = RunState()
        result = _make_result(
            caveats=["could be outdated", "needs more research"],
        )
        report = validate_summary(result, state)
        generic = [i for i in report.issues if i.code == "generic_caveat"]
        assert len(generic) == 2

    def test_empty_caveat_flagged(self):
        state = RunState()
        result = _make_result(
            caveats=[""],
        )
        report = validate_summary(result, state)
        generic = [i for i in report.issues if i.code == "generic_caveat"]
        assert len(generic) == 1


class TestValidateWarns:
    """Tests where validation should emit warnings, not errors."""

    def test_low_source_coverage(self):
        state = RunState(
            fetched_urls={
                "https://a.com/1",
                "https://a.com/2",
                "https://a.com/3",
            },
        )
        result = _make_result(
            sources=[Source(url="https://a.com/1")],
        )
        report = validate_summary(result, state)
        # passed can be True (no errors, only warning)
        warnings = [i for i in report.issues if i.severity == "warning"]
        coverage = [i for i in warnings if i.code == "low_source_coverage"]
        assert len(coverage) == 1
        assert "3" in coverage[0].message
        assert "1" in coverage[0].message

    def test_no_caveats_warns(self):
        state = RunState()
        result = _make_result(caveats=[])
        report = validate_summary(result, state)
        no_cav = [i for i in report.issues if i.code == "no_caveats"]
        assert len(no_cav) == 1
        assert no_cav[0].severity == "warning"
        # No errors, so passed is True
        assert report.passed is True
