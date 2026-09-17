"""Research summarizer agent.

Minimal local-only workflow:
1. Deterministically dispatch the request to one tool (fetch / read_file / search).
2. Run that tool to collect evidence text.
3. Synthesize a structured SummaryResult in a single LLM call.
"""

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
from langchain_openai import ChatOpenAI

# Ensure environment variables from .env are loaded before importing tracing utilities.
load_dotenv()

from langsmith import traceable

from research_summarizer.models import SummaryResult
from research_summarizer.summarizer import summarize_evidence

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
        timeout=timeout,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        }
    )


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


def _run_tool(action: str, tool_input: str) -> str:
    """Run the tool selected by _resolve_action and return its text output."""
    if action == "fetch":
        return fetch_url(tool_input)
    if action == "read_file":
        return read_text_file(tool_input)
    if action == "search":
        return search_web(tool_input)
    raise ValueError(f"Unknown action: {action}")


@traceable(run_type="chain", name="run_agent")
def run_agent(request: str, on_progress: ProgressCallback | None = None) -> SummaryResult:
    """Run the research workflow for a single request and return a structured summary."""
    _fetch_cache.clear()
    model = _build_model()

    action, tool_input = _resolve_action(request)
    _progress(on_progress, "execute", f"{action}: {tool_input}")
    evidence = _run_tool(action, tool_input)

    _progress(on_progress, "summarize", "Summarizing evidence...")
    summary = summarize_evidence(request, evidence, model)

    _progress(on_progress, "done", "Done")
    return summary


def _progress(cb: ProgressCallback | None, stage: str, message: str) -> None:
    """Invoke progress callback if provided."""
    if cb is not None:
        cb(stage, message)
