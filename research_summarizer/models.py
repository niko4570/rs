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
