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
import trafilatura
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
- If a fetch returns `[FETCH_ERROR]`, treat that source as unavailable. Do not cite it or use its content.
"""

# Per-run fetch cache — cleared at the start of each run_agent() call.
_fetch_cache: dict[str, str] = {}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "r", "fbclid", "gclid", "ref", "source", "utm_id",
})


def _now() -> datetime:
    return datetime.now(ZoneInfo("America/Los_Angeles"))


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
    """Search the public web for a research query and return result titles, URLs, and snippets.
    Stale years in freshness-oriented queries are silently corrected."""
    freshness_query = re.search(
        r"\b(latest|recent|today|current|now|news|updates?|this\s+(?:week|month|year))\b",
        query,
        flags=re.IGNORECASE,
    )
    if freshness_query:
        current_year = _now().year
        stale_years = {str(year) for year in range(current_year - 3, current_year)}
        query = re.sub(
            r"\b20\d{2}\b",
            lambda match: str(current_year) if match.group(0) in stale_years else match.group(0),
            query,
        )

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
        system_prompt=SYSTEM_PROMPT,
        name="research_summarizer",
    )


def run_agent(request: str, tools=None) -> str:
    """Run the agent and return the final response text.

    Args:
        request: The user's research query or URL.
        tools: Optional tool list override (passed to build_agent).
    """
    _fetch_cache.clear()
    agent = build_agent(tools=tools)
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request}]},
            config={"recursion_limit": 25},
        )
    except APIError as e:
        return (
            "Model API call failed. Check your API key, account balance, model name, "
            f"and base URL. Provider error: {e}"
        )
    final_message = result["messages"][-1]
    return getattr(final_message, "content", str(final_message))
