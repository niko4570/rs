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
    EvidenceResult,
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

    if action == "search":
        selected = _acquire_search_evidence(request, tool_input, on_progress)
        evidence = format_evidence(selected)
        allowed_urls = {item.url for item in selected.items}
    else:
        evidence = acquire_evidence(action, tool_input)
        allowed_urls = (
            {tool_input} if action == "fetch" and not evidence.startswith("[FETCH_ERROR]") else set()
        )

    _progress(on_progress, "summarize", "Summarizing evidence...")
    raw_answer = summarize_evidence(request, evidence, model)

    result = parse_summary(raw_answer, allowed_urls=allowed_urls)

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
