"""Evidence acquisition: turn a classified input into raw evidence text.

This module is the only place that performs network or filesystem access.
It selects a tool based on the action chosen by input dispatch and returns
the evidence string that is later handed to the summarizer.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import trafilatura
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded before importing tracing utilities.
load_dotenv()

from langsmith import traceable
from tavily import TavilyClient
from tavily.errors import (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    MissingAPIKeyError,
    UsageLimitExceededError,
)
from tavily.errors import TimeoutError as TavilyTimeoutError

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Tavily search: keep the request and the resulting evidence explicitly bounded.
MAX_SEARCH_RESULTS = 5
MAX_SEARCH_CONTENT_CHARS = 4000  # per source
MAX_SEARCH_EVIDENCE_CHARS = 12000  # across all sources
MIN_SEARCH_CONTENT_CHARS = 200  # skip fragments left by the total budget

# Per-run fetch cache — cleared via clear_fetch_cache() at the start of each run.
_fetch_cache: dict[str, str] = {}

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "r", "fbclid", "gclid", "ref", "source", "utm_id",
})


def clear_fetch_cache() -> None:
    """Reset the per-run fetch cache."""
    _fetch_cache.clear()


def _normalize_url(url: str) -> str:
    """Strip tracking query parameters so near-duplicate URLs share a cache key."""
    parsed = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(params)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def _clean_text(text: str, max_chars: int = 6000) -> str:
    """Normalize whitespace while preserving paragraph and line structure.

    Tabs and runs of spaces are collapsed, individual lines are stripped, and
    runs of three or more newlines are reduced to one blank line. Newlines are
    kept so Markdown headings, lists, and paragraph breaks survive.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def _clean_title(text: str, max_chars: int = 200) -> str:
    """Collapse a title onto a single line and bound its length."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


@traceable(run_type="tool", name="search_web")
def search_web(query: str) -> str:
    """Search the public web and return bounded, source-attributed evidence."""
    load_dotenv()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Search failed: missing TAVILY_API_KEY environment variable."

    client = TavilyClient(api_key=api_key)
    try:
        data = client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=MAX_SEARCH_RESULTS,
            include_answer=False,
            include_raw_content="markdown",
            timeout=15,
        )
    except (
        BadRequestError,
        ForbiddenError,
        InvalidAPIKeyError,
        MissingAPIKeyError,
        UsageLimitExceededError,
        TavilyTimeoutError,
        requests.exceptions.RequestException,
    ) as exc:
        return f"Search failed: {exc}"

    raw_results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw_results, list) or not raw_results:
        return "No search results found."

    entries: list[str] = []
    remaining = MAX_SEARCH_EVIDENCE_CHARS
    for result in raw_results[:MAX_SEARCH_RESULTS]:
        if not isinstance(result, dict):
            continue

        title = _clean_title(result.get("title") or "")
        link = (result.get("url") or "").strip()
        if not title or not link:
            continue

        # Prefer full raw content; fall back to Tavily's short content field.
        raw_content = result.get("raw_content")
        if isinstance(raw_content, str) and raw_content.strip():
            content = raw_content
        else:
            fallback = result.get("content")
            content = fallback if isinstance(fallback, str) else ""

        separator = 2 if entries else 0
        header = f"Title: {title}\nURL: {link}\nContent: "
        available = remaining - separator - len(header)
        if available < MIN_SEARCH_CONTENT_CHARS:
            break

        body = _clean_text(content, min(MAX_SEARCH_CONTENT_CHARS, available))
        if not body:
            continue

        entry = f"{header}{body}"
        entries.append(entry)
        remaining -= separator + len(entry)

    return "\n\n".join(entries) if entries else "No search results found."


@traceable(run_type="tool", name="fetch_url")
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
    title_match = re.search(r"<title[^>]*>(.*?)</title>", downloaded, re.IGNORECASE | re.DOTALL)
    title = _clean_title(title_match.group(1)) if title_match else url

    body_clean = _clean_text(body, 8000)
    result = f"Title: {title}\nURL: {url}\nText: {body_clean}"

    _fetch_cache[normalized] = result
    return result


@traceable(run_type="tool", name="read_text_file")
def read_text_file(path: str) -> str:
    """Read a local text or markdown file from the current project for summarization."""
    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (PROJECT_ROOT / file_path).resolve()
    else:
        file_path = file_path.resolve()

    # Security: refuse paths outside the project root
    try:
        file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "Refusing to read outside the current project folder."

    if not file_path.exists() or not file_path.is_file():
        return f"File not found: {path}"

    return _clean_text(file_path.read_text(encoding="utf-8"), 10000)


def acquire_evidence(action: str, tool_input: str) -> str:
    """Run the evidence-acquisition tool selected by input dispatch."""
    if action == "fetch":
        return fetch_url(tool_input)
    if action == "read_file":
        return read_text_file(tool_input)
    if action == "search":
        return search_web(tool_input)
    raise ValueError(f"Unknown action: {action}")
