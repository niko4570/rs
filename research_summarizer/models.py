"""Pydantic output models for the Research Summarizer Agent.

These define the typed contract between the agent and downstream code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Source(BaseModel):
    """A source cited in the summary."""

    title: str | None = None
    url: str
    snippet_used: str | None = None


class SummaryResult(BaseModel):
    """Structured output produced by the research summarizer agent."""

    summary_bullets: list[str] = Field(min_length=4, max_length=7)
    key_details: str
    sources: list[Source]
    caveats: list[str]


class RunState(BaseModel):
    """Records what happened during an agent run.

    Used by the validator to check whether cited sources were actually
    searched, fetched, or read — and whether any failed.
    """

    searched_urls: set[str] = set()
    fetched_urls: set[str] = set()
    failed_fetch_urls: set[str] = set()
    read_files: set[str] = set()


class ValidationIssue(BaseModel):
    """A single issue found during validation."""

    code: str
    message: str
    severity: str = "error"  # "error" or "warning"


class ValidationReport(BaseModel):
    """Result of validating a SummaryResult against RunState."""

    passed: bool
    issues: list[ValidationIssue] = []
