"""LangChain agent for researching and summarizing topics."""

from __future__ import annotations
from typing import Callable

import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import serpapi
import trafilatura
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from openai import APIError
# Ensure environment variables from .env are loaded before importing tracing utilities.
load_dotenv()

from langsmith import traceable

from research_summarizer.critique import critique_output, revise_output
from research_summarizer.executor import execute_step
from research_summarizer.models import RunState, StepResult, SummaryResult
from research_summarizer.parser import ParseError, parse_summary_with_retry
from research_summarizer.planner import plan_research
from research_summarizer.prompts import RESEARCH_AGENT_SYSTEM_PROMPT
from research_summarizer.replanner import replan_step
from research_summarizer.summarizer import summarize_evidence
from research_summarizer.validation import validate_summary

# Per-run fetch cache — cleared at the start of each run_agent() call.
_fetch_cache: dict[str, str] = {}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "r", "fbclid", "gclid", "ref", "source", "utm_id",
})


def _normalize_url(url: str) -> str:
    """Strip tracking query parameters so near-duplicate URLs share a cache key."""
    parsed = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(params)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def _clean_text(text: str, max_chars: int = 6000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


@tool
def search_web(query: str) -> str:
    """Search the public web for a research query and return result titles, URLs, and snippets."""
    load_dotenv()
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "Search failed: missing SERPAPI_API_KEY environment variable."

    client = serpapi.Client(api_key=api_key, timeout=15)
    try:
        data = client.search(
            {
                "engine": "google",
                "q": query,
                "num": 5,
                "hl": "en",
            }
        )
    except (serpapi.HTTPError, serpapi.TimeoutError) as exc:
        return f"Search failed: {exc}"

    if data.get("error"):
        return f"Search failed: {data['error']}"

    results: list[str] = []
    for result in data.get("organic_results", [])[:5]:
        title = _clean_text(result.get("title", ""), 200)
        link = result.get("link", "")
        snippet = _clean_text(result.get("snippet", ""), 300)
        if not title or not link:
            continue
        results.append(f"Title: {title}\nURL: {link}\nSnippet: {snippet}")

    return "\n\n".join(results) if results else "No search results found."


@tool
def fetch_url(url: str) -> str:
    """Fetch a URL and return readable page text for summarization.
    Duplicate fetches (same URL minus tracking params) are served from cache."""
    normalized = _normalize_url(url)

    if normalized in _fetch_cache:
        return f"[CACHED — already fetched this page]\n{_fetch_cache[normalized]}"

    headers = {"User-Agent": "research-summarizer-agent/0.1"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.HTTPError as exc:
        return f"[FETCH_ERROR] Source unavailable: HTTP {exc.response.status_code}"
    except requests.RequestException as exc:
        return f"[FETCH_ERROR] Network failure: {exc}"

    downloaded = response.text

    # Extract clean body text with trafilatura
    body = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )

    if not body:
        return "[FETCH_ERROR] No extractable content from this page."

    # Extract title from raw HTML <title> tag (simple, no BeautifulSoup needed)
    import re as _re
    title_match = _re.search(r"<title[^>]*>(.*?)</title>", downloaded, _re.IGNORECASE | _re.DOTALL)
    title = _clean_text(title_match.group(1), 200) if title_match else url

    body_clean = _clean_text(body, 8000)
    result = f"Title: {title}\nURL: {url}\nText: {body_clean}"

    _fetch_cache[normalized] = result
    return result


@tool
def read_text_file(path: str) -> str:
    """Read a local text or markdown file from the current project for summarization."""
    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (_PROJECT_ROOT / file_path).resolve()
    else:
        file_path = file_path.resolve()

    # Security: refuse paths outside the project root
    try:
        file_path.relative_to(_PROJECT_ROOT)
    except ValueError:
        return "Refusing to read outside the current project folder."

    if not file_path.exists() or not file_path.is_file():
        return f"File not found: {path}"

    return _clean_text(file_path.read_text(encoding="utf-8"), 10000)


# === Tool Registry ===
# Centralized list of all tools the agent can use.
# Add new tools here — they're picked up automatically by build_agent().
_TOOL_REGISTRY: list = [search_web, fetch_url, read_text_file]


def get_tools() -> list:
    """Return a shallow copy of the current tool list.

    Copying prevents callers from accidentally mutating the registry.
    """
    return list(_TOOL_REGISTRY)


def _build_model(timeout: int = 120) -> ChatOpenAI:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    if not all([api_key, base_url, model]):
        raise ValueError(
            "Missing API configuration. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in your environment variables."
        )

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        # temperature=temperature,
        timeout=timeout,
        extra_body={
            "thinking": {
                "type": "disabled", 
            }
        }
    )


def build_agent(tools=None):
    """Create the LangChain research summarizer agent.

    Args:
        tools: Optional tool list override. Defaults to get_tools().
               Pass a custom list for testing.
    """
    if tools is None:
        tools = get_tools()
    return create_agent(
        model=_build_model(),
        tools=tools,
        system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT,
        name="research_summarizer",
    )


# Progress callback type: callable taking (stage, message)
# Stages: plan, execute, replan, summarize, parse, validate, critique, repair, done
ProgressCallback = Callable[[str, str], None]

@traceable(run_type="chain", name="run_agent")
def run_agent(request: str, tools=None, on_progress: ProgressCallback | None = None) -> SummaryResult:
    _fetch_cache.clear()
    model = _build_model()
    state = RunState()
    max_replans = 3
    replan_count = 0
    best_score = 0.0
    max_critique_attempts = 2

    # 1. PLAN
    _progress(on_progress, "plan", f"Planning research for: {request}")
    plan = plan_research(request, model)
    if not plan.steps:
        raise ValueError("Plan produced no steps.")
    _progress(on_progress, "plan", f"Plan ready: {len(plan.steps)} step(s)")

    # 2. EXECUTE
    evidence: list[StepResult] = []
    for step in plan.steps:
        _progress(on_progress, "execute", f"{step.action}: {step.input}")
        result = execute_step(step, state)
        evidence.append(result)

        if result.failed and result.retryable:
            _progress(on_progress, "replan", f"{step.action} failed ({result.error_type}), replanning...")
            replacement = replan_step(
                step, result, plan, state, model,
                replan_count=replan_count, max_replans=max_replans,
            )
            if replacement:
                replan_count += 1
                _progress(on_progress, "replan", f"Trying alternative: {replacement.action} {replacement.input}")
                replan_result = execute_step(replacement, state)
                evidence.append(replan_result)
            else:
                _progress(on_progress, "replan", "No viable alternative found")

    # 3. SUMMARIZE
    _progress(on_progress, "summarize", f"Summarizing {len(evidence)} evidence item(s)...")
    draft_text = summarize_evidence(request, evidence, model)

    # 4. PARSE
    _progress(on_progress, "parse", "Parsing structured output...")
    summary = parse_summary_with_retry(draft_text, model)

    # 5. VALIDATE
    _progress(on_progress, "validate", "Validating summary...")
    report = validate_summary(summary, state)
    if not report.passed:
        _progress(on_progress, "repair", f"Validation failed ({len(report.issues)} issue(s)), repairing...")
        issue_text = "\n".join(
            f"- [{i.code}] {i.message}" for i in report.issues
        )
        repair_request = (
            f"Your summary had validation issues. Fix them.\n\n"
            f"Issues:\n{issue_text}\n\n"
            f"Original request: {request}\n\n"
            f"Original summary draft:\n{draft_text}"
        )
        revised_text = summarize_evidence(repair_request, evidence, model)
        summary = parse_summary_with_retry(revised_text, model)
        _progress(on_progress, "repair", "Validation repair complete")

    # 6. CRITIQUE (Phase 3)
    _progress(on_progress, "critique", "Critiquing summary quality...")
    critique = critique_output(summary, evidence, model)
    _progress(
        on_progress, "critique",
        f"Score: {critique.overall_score:.2f} "
        f"(fidelity={critique.source_fidelity:.2f}, "
        f"diversity={critique.source_diversity:.2f}, "
        f"caveats={critique.caveat_specificity:.2f}, "
        f"completeness={critique.completeness:.2f})"
    )

    # 7. REVISE (bounded loop, max 2 attempts)
    for attempt in range(max_critique_attempts):
        if not critique.should_revise or critique.overall_score >= 0.8:
            break
        if critique.overall_score <= best_score:
            _progress(on_progress, "critique", f"Score not improving ({critique.overall_score:.2f} <= {best_score:.2f}), stopping")
            break

        best_score = critique.overall_score
        _progress(on_progress, "critique", f"Revision attempt {attempt + 1}/2...")

        revised_draft = revise_output(summary, critique, evidence, model)
        summary = parse_summary_with_retry(revised_draft, model)

        critique = critique_output(summary, evidence, model)
        _progress(
            on_progress, "critique",
            f"Post-revision score: {critique.overall_score:.2f}"
        )

    _progress(on_progress, "done", f"Done. Final score: {critique.overall_score:.2f}")
    return summary


def _progress(cb: ProgressCallback | None, stage: str, message: str) -> None:
    """Invoke progress callback if provided."""
    if cb is not None:
        cb(stage, message)
