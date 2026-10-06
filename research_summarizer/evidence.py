"""Evidence acquisition: turn a classified input into bounded evidence.

This module is the only place that performs network or filesystem access.
Search evidence is acquired as structured ``EvidenceItem`` records so a later
selection stage can consume it; ``format_evidence`` renders the bounded,
source-attributed text that the summarizer receives.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
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
SUPPORTED_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown"})

# Tavily search: keep the request and the resulting evidence explicitly bounded.
# Evidence contract: one block per source containing only Title / URL / Content.
MAX_SEARCH_RESULTS = 5
MAX_SEARCH_CONTENT_CHARS = 6000  # per-source content cap
MAX_SEARCH_EVIDENCE_CHARS = 20000  # total evidence cap across all sources
MIN_SEARCH_CONTENT_CHARS = 200  # stop when the remaining budget is too small


@dataclass(frozen=True)
class EvidenceItem:
    """One normalized source of evidence.

    This is the internal contract shared by acquisition, selection, and
    synthesis formatting. Only ``title``, ``url``, and ``content`` are part of
    it; provider-specific metadata never reaches this layer.
    """

    id: str
    title: str
    url: str
    content: str


@dataclass(frozen=True)
class EvidenceResult:
    """Structured outcome of evidence acquisition or selection.

    ``items`` holds normalized sources. ``note`` explains an empty or failed
    acquisition and is rendered only when ``items`` is empty.
    """

    items: tuple[EvidenceItem, ...] = ()
    note: str = ""


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


_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _clean_text(text: str, max_chars: int = 6000) -> str:
    """Normalize whitespace without destroying Markdown structure.

    Headings, paragraphs, and list items are kept, and runs of blank lines are
    reduced to a single blank line. Fenced code blocks (``` or ~~~) are
    preserved verbatim so indentation and internal spacing survive. List item
    indentation is also preserved so nested lists keep their hierarchy.
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    in_fence = False
    blank_run = 0

    for raw_line in text.split("\n"):
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            lines.append(raw_line.rstrip())
            blank_run = 0
            continue

        if in_fence:
            # Code content must keep its exact indentation and spacing.
            lines.append(raw_line)
            continue

        if _LIST_ITEM_RE.match(raw_line):
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]
            body = re.sub(r"[^\S\n]+", " ", raw_line.lstrip()).rstrip()
            line = f"{indent}{body}"
        else:
            line = re.sub(r"[^\S\n]+", " ", raw_line).strip()

        if not line:
            blank_run += 1
            if blank_run <= 1:
                lines.append("")
            continue

        blank_run = 0
        lines.append(line)

    return "\n".join(lines).strip()[:max_chars]


def _clean_title(text: str, max_chars: int = 200) -> str:
    """Collapse a title onto a single line and bound its length."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def _select_search_content(result: dict) -> str:
    """Return the best available text for one Tavily search result.

    Full page content (``raw_content``) is preferred because it carries more
    evidence than the short NLP snippet. Tavily's ``content`` field is used
    only as a fallback when ``raw_content`` is missing or whitespace-only.
    Only the three contract fields (title, url, content) ever leave this
    module; Tavily-specific metadata such as ``score`` or ``favicon`` is not
    returned.
    """
    raw_content = result.get("raw_content")
    if isinstance(raw_content, str) and raw_content.strip():
        return raw_content
    fallback = result.get("content")
    return fallback if isinstance(fallback, str) else ""


def format_evidence(result: EvidenceResult) -> str:
    """Render structured evidence into the bounded, source-attributed text contract.

    Acquisition stays structured, while the summarizer still receives only
    Title / URL / Content blocks.
    """
    if not result.items:
        return result.note or "No evidence available."
    return "\n\n".join(
        f"Title: {item.title}\nURL: {item.url}\nContent: {item.content}"
        for item in result.items
    )


@traceable(run_type="tool", name="search_web")
def search_web_items(query: str) -> EvidenceResult:
    """Search the public web and return bounded, structured evidence."""
    load_dotenv()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return EvidenceResult(
            note="Search failed: missing TAVILY_API_KEY environment variable."
        )

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
        return EvidenceResult(note=f"Search failed: {exc}")

    raw_results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw_results, list) or not raw_results:
        return EvidenceResult(note="No search results found.")

    items: list[EvidenceItem] = []
    remaining = MAX_SEARCH_EVIDENCE_CHARS
    for result in raw_results[:MAX_SEARCH_RESULTS]:
        if not isinstance(result, dict):
            continue

        title = _clean_title(result.get("title") or "")
        link = (result.get("url") or "").strip()
        if not title or not link:
            continue

        content = _select_search_content(result)

        separator = 2 if items else 0
        header = f"Title: {title}\nURL: {link}\nContent: "
        available = remaining - separator - len(header)
        if available < MIN_SEARCH_CONTENT_CHARS:
            break

        body = _clean_text(content, min(MAX_SEARCH_CONTENT_CHARS, available))
        if not body:
            continue

        item = EvidenceItem(id=f"S{len(items) + 1}", title=title, url=link, content=body)
        items.append(item)
        remaining -= separator + len(header) + len(body)

    if not items:
        return EvidenceResult(note="No search results found.")
    return EvidenceResult(items=tuple(items))


def search_web(query: str) -> str:
    """Search the public web and return bounded, source-attributed evidence text."""
    return format_evidence(search_web_items(query))


@traceable(run_type="tool", name="fetch_url")
def fetch_url(url: str) -> str:
    """Fetch a URL and return readable page text for summarization.
    Duplicate fetches (same URL minus tracking params) are served from cache."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "[FETCH_ERROR] Invalid URL. Only HTTP(S) URLs are supported."

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

    if file_path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
        return "Unsupported file type. Only .txt, .md, and .markdown files are supported."

    if not file_path.exists() or not file_path.is_file():
        return f"File not found: {path}"

    try:
        return _clean_text(file_path.read_text(encoding="utf-8"), 10000)
    except UnicodeDecodeError:
        return "File is not valid UTF-8 text."


def acquire_evidence(action: str, tool_input: str) -> str:
    """Run the evidence-acquisition tool selected by input dispatch."""
    if action == "fetch":
        return fetch_url(tool_input)
    if action == "read_file":
        return read_text_file(tool_input)
    if action == "search":
        return search_web(tool_input)
    raise ValueError(f"Unknown action: {action}")
