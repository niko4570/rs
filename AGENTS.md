# AGENTS.md — Research Summarizer Agent

## Project Overview

A LangChain-based research summarizer agent that accepts a topic, URL, or local file path and returns a structured summary with sources, key details, and caveats.

- **Language:** Python 3.11+
- **Framework:** LangChain (`create_agent`, not LangGraph)
- **LLM:** OpenAI-compatible API (DeepSeek primary, also OpenAI)
- **Search:** SerpApi (Google)
- **Parsing:** trafilatura (HTML/text extraction), Python stdlib (local files)
- **Tracing:** LangSmith (optional)
- **Linting:** Ruff, line-length 100
- **Testing:** `pytest` with `pytest-mock`
- **Package manager:** pip (editable install: `pip install -e .`)
- **CLI entry point:** `research-agent` (also `python -m research_summarizer.cli`)

## Architecture

```
research_summarizer/
  __init__.py   — public exports: build_agent, run_agent
  agent.py      — tools, model builder, agent factory, run loop
  cli.py        — argparse entry point
tests/
  test_tools.py — pytest tests for search_web, fetch_url, read_text_file, _normalize_url
```

**Agent flow:** `cli.py` calls `run_agent(request)` → clears fetch cache → `build_agent()` creates a LangChain agent with 3 tools → `agent.invoke()` runs the agent loop (max 25 recursion steps) → returns final message content.

**Three tools** registered on the agent:

1. `search_web(query)` — SerpApi Google search, auto-corrects stale years in freshness queries
2. `fetch_url(url)` — HTTP GET + trafilatura text extraction, caches per-run with URL normalization
3. `read_text_file(path)` — reads local .txt/.md files, refuses paths outside project root

## Development Workflow

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and fill in:

- `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL` (required)
- `SERPAPI_API_KEY` (required for web search)
- LangSmith vars (optional)

### Git workflow

- **Always branch before changes.** Never commit directly to `main`.
- Repo: `https://github.com/niko4570/rs`
- Branch naming: descriptive, kebab-case (e.g. `fix-fetch-caching`, `add-tool-timeout`)

### Running

```bash
# CLI
research-agent "Summarize the latest AI news"
research-agent "https://example.com/article"
research-agent "README.md"

# Or as module
python -m research_summarizer.cli "query"
```

### Testing

```bash
pytest
# or single file
pytest tests/test_tools.py
```

Tests use `pytest` with `pytest-mock`. The test suite covers:

- `search_web`: missing API key, result parsing, stale-year correction, historical year preservation, error reporting
- `fetch_url`: page text extraction, cache hits (same URL + tracking-param variants), HTTP errors, network errors, errors-not-cached
- `read_text_file`: reading project files, refusing out-of-project paths, relative path resolution
- `_normalize_url`: UTM stripping, tracking param removal, preserving valid params, clean URLs
- tool registry and agent construction: `get_tools()`, `_TOOL_REGISTRY`, `build_agent()` tool overrides

### Linting

```bash
ruff check .
```

## Key Patterns & Design Decisions

### Per-run fetch cache (`_fetch_cache`)

A module-level `dict[str, str]` that lives for one `run_agent()` call. Cleared at the top of `run_agent()`. This is the **primary mechanism for preventing duplicate work** — it replaces multiple prompt-rule patches.

- URL normalization strips tracking params (`utm_*`, `fbclid`, `r`, `ref`, etc.) so near-duplicate URLs share a cache key
- Cache hits return `[CACHED — already fetched this page]` prefix — the model sees it already has the content
- Failed fetches are **not cached** — prevents the model from "trusting" dead sources later
- HTTP errors are surfaced as plain text (`FETCH ERROR` / `URL fetch failed`) so LangSmith shows them but the agent can continue

### Stale-year correction in `search_web`

For queries containing freshness words (`latest`, `recent`, `today`, `current`, `now`, `news`, `updates`, `this week/month/year`), `search_web` rewrites years that are 1-3 years stale to the current year. Historical queries (years >3 back or no freshness words) pass through unchanged.

This moves the correction **into the tool** rather than depending on the model to call and remember a time tool — state in tools beats state in prompts.

### DeepSeek v4 thinking mode

DeepSeek v4 models require `thinking` disabled. The `_build_model()` function detects `api.deepseek.com` in the base URL + `deepseek-v4-*` model prefix and injects `extra_body={"thinking": {"type": "disabled"}}`. Other model/provider combinations pass through without this option.

### Agent recursion limit

Set to 25 (`config={"recursion_limit": 25}`). This is intentionally generous — the fetch cache should reduce redundant tool calls, not the recursion limit.

### Error handling

- `run_agent()` catches `openai.APIError` and returns a user-friendly diagnostic
- Tool errors (`fetch_url` network/HTTP failures) return error text — the agent loop continues
- `read_text_file` refuses paths outside the project root for safety

## Common Pitfalls

1. **Don't add prompt-level rules for things tools can handle.** The fetch cache, stale-year correction, and URL normalization all live in the tools. Prompt rules degrade under attention decay; tool behavior doesn't.

2. **Don't append `after:<today>` to all searches.** It excludes legitimate pages and breaks normal research queries. Stale-year correction is targeted — only freshness queries get rewritten.

3. **Don't add LangGraph unless the workflow requires strict multi-step orchestration.** The current `create_agent` loop with 3 tools is intentionally simple.

4. **DeepSeek v4 models will 400 without `thinking: disabled`.** If you change the model, verify the `_build_model()` detection still works.

5. **The agent runs open-loop within a single invocation.** There's no persistent memory across `run_agent()` calls. Each call gets a fresh cache and fresh agent instance.

6. **Tests use `pytest`, not `unittest`.** The repository uses `pytest` with `pytest-mock` and prefers simple fixture usage.

7. **The `.env` file is gitignored.** Never commit API keys. Use `.env.example` as a template.

## Context Window & Attention Management

The known failure mode: as context grows past 8-10 turns with full page texts, earlier tool results fall out of the model's attention window. The model then repeats fetches, chases index pages, and over-fetches.

Mitigations in place:

- Fetch cache eliminates duplicate HTTP calls
- `[CACHED]` prefix tells the model it already has the content (shorter context than re-fetching)
- `_clean_text()` caps fetch output at 8,000 chars and search snippets at 300 chars
- LangSmith tracing is the observability layer — inspect traces there when the agent behaves unexpectedly
