"""Validation for structured research summaries.

Checks a SummaryResult against RunState to catch hallucinations,
failed-source citations, and weak caveats before delivery.
"""

from __future__ import annotations

from research_summarizer.models import (
    RunState,
    SummaryResult,
    ValidationIssue,
    ValidationReport,
)

GENERIC_CAVEAT_PATTERNS: list[str] = [
    "may be incomplete",
    "could be outdated",
    "might be outdated",
    "may be biased",
    "could be biased",
    "needs more research",
    "further research needed",
    "more research is needed",
    "information may not be",
    "subject to change",
    "may not be accurate",
    "could be wrong",
]


def _is_generic_caveat(caveat: str) -> bool:
    """Check if a caveat is a generic, non-specific phrase."""
    normalized = caveat.strip().lower()
    if not normalized:
        return True
    for pattern in GENERIC_CAVEAT_PATTERNS:
        if pattern in normalized:
            return True
    return False


def validate_summary(result: SummaryResult, state: RunState) -> ValidationReport:
    """Validate a SummaryResult against what actually happened during the run.

    Args:
        result: The parsed summary to validate.
        state: RunState tracking what was searched, fetched, failed, and read.

    Returns:
        A ValidationReport. If passed=True, the result is clean.
        If passed=False, issues contains specific problems found.
    """
    issues: list[ValidationIssue] = []

    # 1. Source integrity: every cited URL must be discoverable in state
    all_known_urls = state.searched_urls | state.fetched_urls | state.read_files
    for source in result.sources:
        url = source.url
        # Check exact match first, then check if any known URL contains this one
        # (model might cite a shorter form)
        if url not in all_known_urls and not any(
            url in known or known in url for known in all_known_urls
        ):
            issues.append(
                ValidationIssue(
                    code="hallucinated_source",
                    message=f"Cited source not found in searched/fetched/read URLs: {url}",
                    severity="error",
                )
            )

    # 2. Failed-source citation: don't cite sources that returned errors
    for source in result.sources:
        if source.url in state.failed_fetch_urls:
            issues.append(
                ValidationIssue(
                    code="cited_failed_source",
                    message=f"Cited source that failed to fetch: {source.url}",
                    severity="error",
                )
            )

    # 3. Generic caveats: require specificity
    for caveat in result.caveats:
        if _is_generic_caveat(caveat):
            issues.append(
                ValidationIssue(
                    code="generic_caveat",
                    message=f'Caveat is too generic: "{caveat}"',
                    severity="error",
                )
            )

    # 4. Coverage warning: if we fetched multiple pages but only cited one
    fetched_count = len(state.fetched_urls)
    cited_urls = {s.url for s in result.sources}
    cited_fetched = cited_urls & state.fetched_urls
    if fetched_count > 1 and len(cited_fetched) < fetched_count:
        issues.append(
            ValidationIssue(
                code="low_source_coverage",
                message=(
                    f"Fetched {fetched_count} pages but only cited "
                    f"{len(cited_fetched)}. Some sources may have been ignored."
                ),
                severity="warning",
            )
        )

    # 5. Empty caveats (no issues at all means nothing to report)
    if not result.caveats:
        issues.append(
            ValidationIssue(
                code="no_caveats",
                message="No caveats provided. Every research result should note limitations.",
                severity="warning",
            )
        )

    passed = not any(i.severity == "error" for i in issues)
    return ValidationReport(passed=passed, issues=issues)
