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


class BulletCitation(BaseModel):
    """An excerpt supporting one zero-based summary bullet."""

    bullet_index: int = Field(ge=0)
    source_url: str | None = None
    excerpt: str = Field(min_length=1, max_length=500)


class SummaryResult(BaseModel):
    """Structured output produced by the research summarizer agent."""

    summary_bullets: list[str] = Field(min_length=4, max_length=7)
    key_details: str
    sources: list[Source]
    caveats: list[str]
    citations: list[BulletCitation] = Field(default_factory=list)
