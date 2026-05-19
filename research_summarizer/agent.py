"""LangChain agent for researching and summarizing topics."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
import serpapi
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from openai import APIError


SYSTEM_PROMPT = """You are a Research Summarizer Agent.

Your job is to help users understand a topic from source material.

Workflow:
1. If the user gives URLs, fetch them before summarizing.
2. If the user gives a broad topic, search the web, then fetch the most relevant pages.
3. Compare sources instead of trusting the first result.
4. Separate facts from uncertainty.
5. Prefer concise summaries with citations.

Output format:
- Summary: 4-7 bullets
- Key details: facts, dates, names, numbers, and tradeoffs
- Sources: list source titles or URLs used
- Caveats: what may be missing, outdated, or uncertain

Do not invent citations. If sources are weak or unavailable, say so.
"""

# Per-run fetch cache — cleared at the start of each run_agent() call.
# Prevents duplicate fetches and keeps context short.
_fetch_cache: dict[str, str] = {}

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
def current_time() -> str:
    """Get the real current date and time. Call this whenever you need to know
    what date it is right now — especially for time-sensitive or recent-event questions."""
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return f"Current date: {now:%Y-%m-%d} ({now:%A}). Time: {now:%H:%M:%S} {now:%Z}."


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
        # HTTP errors (4xx, 5xx) fail the tool so the model can't trust dead sources.
        # Not cached, so the model can't retrieve the failure as "content" later.
        raise RuntimeError(f"URL fetch failed: HTTP {exc.response.status_code}") from exc
    except requests.RequestException as exc:
        return f"URL fetch failed (network): {exc}"

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = _clean_text(soup.title.get_text(" "), 200) if soup.title else url
    body = _clean_text(soup.get_text(" "), 8000)
    result = f"Title: {title}\nURL: {url}\nText: {body}"

    _fetch_cache[normalized] = result
    return result


@tool
def read_text_file(path: str) -> str:
    """Read a local text or markdown file from the current project for summarization."""
    file_path = Path(path).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if cwd not in file_path.parents and file_path != cwd:
        return "Refusing to read outside the current project folder."
    if not file_path.exists() or not file_path.is_file():
        return f"File not found: {path}"
    return _clean_text(file_path.read_text(encoding="utf-8"), 10000)


def _build_model(temperature: float = 0.0, timeout: int = 120) -> ChatOpenAI:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model_name = os.getenv("OPENAI_MODEL")

    if not all([api_key, base_url, model_name]):
        raise ValueError(
            "Missing API configuration. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in your environment variables."
        )

    model_options = {}
    if "api.deepseek.com" in base_url and model_name.startswith("deepseek-v4"):
        model_options["extra_body"] = {"thinking": {"type": "disabled"}}

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=temperature,
        timeout=timeout,
        **model_options,
    )


def build_agent():
    """Create the LangChain research summarizer agent."""
    return create_agent(
        model=_build_model(),
        tools=[current_time, search_web, fetch_url, read_text_file],
        system_prompt=SYSTEM_PROMPT,
        name="research_summarizer",
    )


def run_agent(request: str) -> str:
    """Run the agent and return the final response text."""
    _fetch_cache.clear()
    agent = build_agent()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request}]},
            config={"recursion_limit": 15},
        )
    except APIError as e:
        return (
            "Model API call failed. Check your API key, account balance, model name, "
            f"and base URL. Provider error: {e}"
        )
    final_message = result["messages"][-1]
    return getattr(final_message, "content", str(final_message))
