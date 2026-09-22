"""Research summarizer workflow.

Top-level data flow:

    Input
      -> Input Dispatch        (_resolve_action)
      -> Evidence Acquisition  (search_web_items / acquire_evidence)
      -> Jev selection         (judge_evidence, search only)
      -> Evidence
      -> Summarizer            (one LLM call)
      -> Parser                (parse_summary)
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
    acquire_evidence,
    clear_fetch_cache,
    format_evidence,
    search_web_items,
)
from research_summarizer.jev import judge_evidence
from research_summarizer.models import SummaryResult
from research_summarizer.parser import parse_summary
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
def run_agent(request: str, on_progress: ProgressCallback | None = None) -> SummaryResult:
    """Run the research workflow for a single request and return a structured summary."""
    clear_fetch_cache()
    model = build_model()

    action, tool_input = _resolve_action(request)
    _progress(on_progress, "execute", f"{action}: {tool_input}")

    if action == "search":
        evidence = _acquire_search_evidence(request, tool_input, on_progress)
    else:
        evidence = acquire_evidence(action, tool_input)

    _progress(on_progress, "summarize", "Summarizing evidence...")
    raw_answer = summarize_evidence(request, evidence, model)

    result = parse_summary(raw_answer)

    _progress(on_progress, "done", "Done")
    return result


def _acquire_search_evidence(
    request: str, query: str, on_progress: ProgressCallback | None
) -> str:
    """Acquire search evidence, let Jev select sources, then format for synthesis."""
    acquired = search_web_items(query)
    if not acquired.items:
        return format_evidence(acquired)

    _progress(on_progress, "judge", "Selecting relevant evidence...")
    selected = judge_evidence(request, acquired.items)
    return format_evidence(selected)


def _progress(cb: ProgressCallback | None, stage: str, message: str) -> None:
    """Invoke progress callback if provided."""
    if cb is not None:
        cb(stage, message)
