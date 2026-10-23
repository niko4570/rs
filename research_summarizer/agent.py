"""Research summarizer workflow.

Top-level data flow:

    Input
      -> Input Dispatch        (_resolve_action)
      -> Evidence Acquisition  (search_web_items / acquire_evidence)
      -> Jev selection         (judge_evidence, search only)
      -> Evidence
      -> Summarizer            (one LLM call)
      -> Parser                (parse_synthesis + source ID resolution)
      -> SummaryResult
"""

from __future__ import annotations

import re
from collections.abc import Callable

from dotenv import load_dotenv

# Ensure environment variables from .env are loaded before importing tracing utilities.
load_dotenv()

from langsmith import traceable

from research_summarizer.evidence import (
    FILE_ERROR_PREFIX,
    EvidenceResult,
    acquire_evidence,
    clear_fetch_cache,
    format_synthesis_evidence,
    search_web_items,
)
from research_summarizer.jev import judge_evidence
from research_summarizer.models import SourceContent, SummaryResult
from research_summarizer.parser import parse_synthesis
from research_summarizer.summarizer import build_model, summarize_evidence

# Progress callback type: callable taking (stage, message)
ProgressCallback = Callable[[str, str], None]


def _resolve_action(request: str) -> tuple[str, str]:
    """Deterministically map a request to one tool action and its input.

    - http(s) URLs -> fetch
    - local .txt/.md/.markdown paths -> read_file
    - anything else -> search (topic)
    """
    request = request.strip()

    url_match = re.search(r"https?://\S+", request)
    if url_match:
        return "fetch", url_match.group(0).rstrip(".,;:!?\"')]")

    file_match = re.search(r"[\w./-]+\.(?:txt|md|markdown)\b", request, flags=re.IGNORECASE)
    if file_match:
        return "read_file", file_match.group(0)

    return "search", request


@traceable(run_type="chain", name="run_agent")
def run_agent(
    request: str,
    on_progress: ProgressCallback | None = None,
    *,
    action: str | None = None,
) -> SummaryResult:
    """Run the research workflow for a single request and return a structured summary."""
    clear_fetch_cache()
    model = build_model()

    if action is None:
        action, tool_input = _resolve_action(request)
    elif action in {"search", "fetch", "read_file"}:
        tool_input = request
    else:
        raise ValueError(f"Unknown action: {action}")
    _progress(on_progress, "execute", f"{action}: {tool_input}")

    sources: dict[str, SourceContent] = {}
    if action == "search":
        selected = _acquire_search_evidence(request, tool_input, on_progress)
        sources = {
            f"S{index}": SourceContent(title=item.title, url=item.url, content=item.content)
            for index, item in enumerate(selected.items, start=1)
        }
        evidence = format_synthesis_evidence(sources, selected.note or "")
    else:
        acquired = acquire_evidence(action, tool_input)
        if action == "fetch" and not acquired.startswith("[FETCH_ERROR]"):
            title = re.search(r"^Title: (.*)$", acquired, flags=re.MULTILINE)
            sources["S1"] = SourceContent(
                title=title.group(1) if title else None, url=tool_input,
                content=acquired.split("\nText: ", 1)[-1],
            )
        elif action == "read_file" and acquired.strip() and not acquired.startswith(FILE_ERROR_PREFIX):
            sources["S1"] = SourceContent(content=acquired)
        evidence = format_synthesis_evidence(sources, acquired)

    _progress(on_progress, "summarize", "Summarizing evidence...")
    raw_answer = summarize_evidence(request, evidence, model)

    result = parse_synthesis(raw_answer, sources)

    _progress(on_progress, "done", "Done")
    return result


def _acquire_search_evidence(
    request: str, query: str, on_progress: ProgressCallback | None
) -> EvidenceResult:
    """Acquire search evidence and let Jev select sources for synthesis."""
    acquired = search_web_items(query)
    if not acquired.items:
        return acquired

    _progress(on_progress, "judge", "Selecting relevant evidence...")
    selected = judge_evidence(request, acquired.items)
    return selected


def _progress(cb: ProgressCallback | None, stage: str, message: str) -> None:
    """Invoke progress callback if provided."""
    if cb is not None:
        cb(stage, message)
