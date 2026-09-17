"""Tests for CLI formatting — verifies CLI compatibility without an LLM."""

from research_summarizer.cli import _format_result
from research_summarizer.models import Source, SummaryResult


def test_format_result_has_all_sections():
    result = SummaryResult(
        summary_bullets=["Point 1", "Point 2", "Point 3", "Point 4"],
        key_details="Some key facts.",
        sources=[Source(title="Example", url="https://example.com/article")],
        caveats=["Limited to a single source"],
    )

    output = _format_result(result)

    assert "Summary:" in output
    assert "- Point 1" in output
    assert "Key details: Some key facts." in output
    assert "Sources:" in output
    assert "Example (https://example.com/article)" in output
    assert "Caveats:" in output
    assert "- Limited to a single source" in output


def test_format_result_omits_empty_optional_sections():
    result = SummaryResult(
        summary_bullets=["Point 1", "Point 2", "Point 3", "Point 4"],
        key_details="Some key facts.",
        sources=[],
        caveats=[],
    )

    output = _format_result(result)

    assert "Sources:" not in output
    assert "Caveats:" not in output
