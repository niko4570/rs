"""Pydantic output models for the Research Summarizer Agent.

These define the typed contract between the agent and downstream code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class SourceContent(BaseModel):
    """Python-owned source metadata and acquired content for one synthesis input."""

    title: str | None = None
    url: str | None = None
    content: str


class SynthesisCitation(BaseModel):
    """The model selects a source ID; it cannot supply source metadata."""

    model_config = ConfigDict(extra="forbid")

    bullet_index: int = Field(ge=0)
    source_id: str
    excerpt: str = Field(min_length=1, max_length=500)


class SynthesisResult(BaseModel):
    """Internal model output, resolved into the public SummaryResult by Python."""

    model_config = ConfigDict(extra="forbid")

    summary_bullets: list[str] = Field(min_length=4, max_length=7)
    key_details: str
    caveats: list[str]
    citations: list[SynthesisCitation]
