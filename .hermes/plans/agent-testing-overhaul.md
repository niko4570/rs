# Agent Testing Overhaul — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace unittest with pytest, add real agent integration tests (tool selection, multi-step flow, output format) using mocked LLM responses.

**Architecture:** Three test layers — tool unit tests (existing, converted to pytest), agent integration tests (new, LLM mocked via `patch.object(ChatOpenAI, 'invoke')`), and end-to-end (LangSmith evals, future). The integration layer controls what the LLM "thinks" at each step by injecting `AIMessage` objects with predetermined `tool_calls` or final content.

**Tech Stack:** pytest, pytest-mock, langchain-core, unittest.mock.patch

---

## The Key Insight: How to Mock the Agent's LLM

The agent loop works like this (LangGraph under the hood):

```
HumanMessage → [LLM decides: tool_call] → agent executes tool → ToolMessage → [LLM decides: final_answer] → done
```

To test it, you intercept `ChatOpenAI.invoke` and return controlled `AIMessage` objects:

```python
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

fake_responses = iter([
    # Step 1: LLM "chooses" to call search_web
    AIMessage(content='', tool_calls=[{
        'name': 'search_web', 'args': {'query': 'latest AI news'},
        'id': 'call_1', 'type': 'tool_call'
    }]),
    # Step 2: LLM sees tool result, produces final answer
    AIMessage(content='Summary: ...\nSources: ...\nCaveats: ...'),
])

with patch.object(ChatOpenAI, 'invoke', lambda self, input, *a, **kw: next(fake_responses)):
    agent = build_agent()
    result = agent.invoke(
        {'messages': [HumanMessage(content='summarize latest AI news')]},
        config={'recursion_limit': 25},
    )
    # Verify tool was called, output format, etc.
```

This lets you test:
- **Tool selection**: Does the agent pick `search_web` for a topic query? `fetch_url` for a URL?
- **Multi-step flow**: search → fetch → summarize — does it chain tools correctly?
- **Output format**: Does the final message have Summary / Key details / Sources / Caveats?
- **Error handling**: Does it handle `[FETCH_ERROR]` / `[CACHED]` / `Search failed` properly?
- **Cache behavior**: Does `_fetch_cache` prevent duplicate LLM calls?

---

## Task 1: Add pytest dependency

**Objective:** Install pytest and pytest-mock as dev dependencies

**Files:**
- Modify: `pyproject.toml`

**Changes:**

```toml
# Add under [project]
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.0",
]
```

Then: `pip install -e ".[dev]"`

---

## Task 2: Create pytest conftest with shared fixtures

**Objective:** Extract common test setup into reusable fixtures

**Files:**
- Create: `tests/conftest.py`

```python
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from research_summarizer.agent import _PROJECT_ROOT


@pytest.fixture
def temp_project_root():
    """Temporary directory patched as _PROJECT_ROOT."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch("research_summarizer.agent._PROJECT_ROOT", root.resolve()):
            yield root


@pytest.fixture(autouse=True)
def clear_fetch_cache():
    """Clear the per-run fetch cache before every test."""
    from research_summarizer import agent

    agent._fetch_cache.clear()
    yield
    agent._fetch_cache.clear()


@pytest.fixture
def mock_serpapi_key():
    """Set SERPAPI_API_KEY in environment for search_web tests."""
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
        yield


@pytest.fixture
def no_serpapi_key():
    """Ensure SERPAPI_API_KEY is absent."""
    with patch.dict("os.environ", {}, clear=True):
        yield
```

---

## Task 3: Convert tool tests from unittest to pytest

**Objective:** Rewrite existing tests in pytest style (plain functions, fixtures, `assert` instead of `self.assertX`)

**Files:**
- Modify: `tests/test_tools.py` (rewrite)

Key conversions:

| unittest | pytest |
|---|---|
| `class XTests(unittest.TestCase):` | Plain module-level functions |
| `def setUp(self):` | `@pytest.fixture(autouse=True)` |
| `self.assertIn(a, b)` | `assert a in b` |
| `self.assertEqual(a, b)` | `assert a == b` |
| `with tempfile.TemporaryDirectory() as tmp:` | `temp_project_root` fixture |
| `@patch.dict("os.environ", ...)` | `mock_serpapi_key` / `no_serpapi_key` fixtures |
| `@patch("module.Class")` | `mocker.patch("module.Class")` (pytest-mock) |

Example conversion:

```python
# BEFORE (unittest)
class SearchWebTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("research_summarizer.agent.load_dotenv")
    def test_requires_serpapi_key(self, mock_load_dotenv):
        result = search_web.invoke({"query": "example story"})
        self.assertIn("missing SERPAPI_API_KEY", result)

# AFTER (pytest)
def test_search_web_requires_api_key(no_serpapi_key, mocker):
    mock_load_dotenv = mocker.patch("research_summarizer.agent.load_dotenv")
    result = search_web.invoke({"query": "example story"})
    assert "missing SERPAPI_API_KEY" in result
    mock_load_dotenv.assert_called_once()
```

---

## Task 4: Write a helper for mocking agent LLM responses

**Objective:** Create a reusable helper that builds mock LLM sequences for agent tests

**Files:**
- Create: `tests/agent_test_utils.py`

```python
"""Helpers for testing the LangChain agent with mocked LLM responses."""

from collections.abc import Iterator
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


def make_tool_call_msg(tool_name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    """Create an AIMessage that instructs the agent to call a tool."""
    return AIMessage(
        content="",
        tool_calls=[{
            "name": tool_name,
            "args": args,
            "id": call_id,
            "type": "tool_call",
        }],
    )


def make_final_msg(content: str) -> AIMessage:
    """Create an AIMessage representing the agent's final answer."""
    return AIMessage(content=content)


def mock_agent_llm(responses: list[AIMessage]):
    """
    Context manager that patches ChatOpenAI.invoke to return the given
    responses in sequence. Use in a `with` block.
    """
    it = iter(responses)
    return patch.object(
        ChatOpenAI, "invoke",
        lambda self, input, *args, **kwargs: next(it),
    )
```

---

## Task 5: Write agent integration tests — tool selection

**Objective:** Test that the agent calls the right tool for different input types

**Files:**
- Create: `tests/test_agent.py`

```python
"""Integration tests for the agent — tool selection, multi-step flow, output format."""

from unittest.mock import patch

from langchain_core.messages import HumanMessage

from research_summarizer.agent import build_agent
from tests.agent_test_utils import make_final_msg, make_tool_call_msg, mock_agent_llm


class TestAgentToolSelection:
    """Verify the agent picks the correct tool based on user input."""

    def test_topic_query_calls_search_web(self, mocker):
        """A broad topic query should trigger search_web."""
        mock_search = mocker.patch(
            "research_summarizer.agent.search_web.invoke",
            return_value="Title: AI News\nURL: https://example.com\nSnippet: ...",
        )

        with mock_agent_llm([
            make_tool_call_msg("search_web", {"query": "latest AI breakthroughs"}),
            make_final_msg("Summary: ...\nSources: example.com\nCaveats: ..."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="summarize latest AI breakthroughs")]},
                config={"recursion_limit": 25},
            )

        mock_search.assert_called_once_with({"query": "latest AI breakthroughs"})
        assert "example.com" in result["messages"][-1].content

    def test_url_input_calls_fetch_url(self, mocker):
        """A URL input should trigger fetch_url, not search_web."""
        mock_fetch = mocker.patch(
            "research_summarizer.agent.fetch_url.invoke",
            return_value="Title: Article\nURL: https://example.com/article\nText: Content here.",
        )

        with mock_agent_llm([
            make_tool_call_msg("fetch_url", {"url": "https://example.com/article"}),
            make_final_msg("Summary: ...\nSources: example.com/article\nCaveats: ..."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="https://example.com/article")]},
                config={"recursion_limit": 25},
            )

        mock_fetch.assert_called_once_with({"url": "https://example.com/article"})
```

---

## Task 6: Write agent integration tests — multi-step flow

**Objective:** Test that the agent can chain tools (search → fetch → summarize)

**Files:**
- Modify: `tests/test_agent.py` (add to class or new class)

```python
class TestAgentMultiStepFlow:
    """Verify the agent chains multiple tool calls correctly."""

    def test_search_then_fetch_flow(self, mocker):
        """Agent should search, then fetch top results, then summarize."""
        mock_search = mocker.patch(
            "research_summarizer.agent.search_web.invoke",
            return_value=(
                "Title: Article 1\nURL: https://a.com/1\nSnippet: ...\n\n"
                "Title: Article 2\nURL: https://a.com/2\nSnippet: ..."
            ),
        )
        mock_fetch = mocker.patch(
            "research_summarizer.agent.fetch_url.invoke",
            side_effect=[
                "Title: A1\nURL: https://a.com/1\nText: Content one.",
                "Title: A2\nURL: https://a.com/2\nText: Content two.",
            ],
        )

        with mock_agent_llm([
            # Step 1: search
            make_tool_call_msg("search_web", {"query": "climate change 2025"}, call_id="c1"),
            # Step 2: fetch first result
            make_tool_call_msg("fetch_url", {"url": "https://a.com/1"}, call_id="c2"),
            # Step 3: fetch second result
            make_tool_call_msg("fetch_url", {"url": "https://a.com/2"}, call_id="c3"),
            # Step 4: final answer
            make_final_msg("Summary: ...\nSources: a.com/1, a.com/2\nCaveats: ..."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="research climate change 2025")]},
                config={"recursion_limit": 25},
            )

        assert mock_search.call_count == 1
        assert mock_fetch.call_count == 2
        final = result["messages"][-1].content
        assert "a.com/1" in final
        assert "a.com/2" in final
```

---

## Task 7: Write agent integration tests — output format

**Objective:** Verify the agent's final output includes all required sections

**Files:**
- Modify: `tests/test_agent.py` (add class)

```python
class TestAgentOutputFormat:
    """Verify the agent produces properly formatted final output."""

    def test_output_has_required_sections(self, mocker):
        """Final answer should include Summary, Sources, Caveats."""
        mocker.patch(
            "research_summarizer.agent.search_web.invoke",
            return_value="Title: T\nURL: https://x.com\nSnippet: ...",
        )

        good_output = (
            "Summary:\n- Bullet 1\n- Bullet 2\n\n"
            "Key details: Fact A, Fact B\n\n"
            "Sources:\n- https://x.com\n\n"
            "Caveats: Some info may be outdated."
        )

        with mock_agent_llm([
            make_tool_call_msg("search_web", {"query": "test"}, call_id="c1"),
            make_final_msg(good_output),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="research test topic")]},
                config={"recursion_limit": 25},
            )

        final = result["messages"][-1].content
        assert "Summary" in final
        assert "Sources" in final
        assert "Caveats" in final

    def test_mentions_caveats_when_no_results(self, mocker):
        """When search returns nothing, agent should note it in caveats."""
        mocker.patch(
            "research_summarizer.agent.search_web.invoke",
            return_value="No search results found.",
        )

        with mock_agent_llm([
            make_tool_call_msg("search_web", {"query": "nonexistent topic xyz123"}, call_id="c1"),
            make_final_msg("Summary: No results found.\nSources: none\nCaveats: Search returned no results."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="research nonexistent topic xyz123")]},
                config={"recursion_limit": 25},
            )

        final = result["messages"][-1].content
        assert "no results" in final.lower() or "Caveats" in final
```

---

## Task 8: Write agent integration tests — error handling

**Objective:** Verify the agent handles tool errors gracefully

**Files:**
- Modify: `tests/test_agent.py` (add class)

```python
class TestAgentErrorHandling:
    """Verify the agent handles tool errors without crashing."""

    def test_handles_fetch_error(self, mocker):
        """Agent should continue when fetch_url returns [FETCH_ERROR]."""
        mocker.patch(
            "research_summarizer.agent.fetch_url.invoke",
            return_value="[FETCH_ERROR] Source unavailable: HTTP 403",
        )

        with mock_agent_llm([
            make_tool_call_msg("fetch_url", {"url": "https://paywall.com"}, call_id="c1"),
            make_final_msg("Summary: Could not access source.\nSources: paywall.com (inaccessible)\nCaveats: Source was behind paywall."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="https://paywall.com")]},
                config={"recursion_limit": 25},
            )

        final = result["messages"][-1].content
        # Agent should complete without exception
        assert len(final) > 0

    def test_handles_search_error(self, mocker):
        """Agent should handle missing API key gracefully."""
        mocker.patch(
            "research_summarizer.agent.search_web.invoke",
            return_value="Search failed: missing SERPAPI_API_KEY",
        )

        with mock_agent_llm([
            make_tool_call_msg("search_web", {"query": "test"}, call_id="c1"),
            make_final_msg("Summary: Cannot search — API key missing.\nSources: none\nCaveats: API configuration issue."),
        ]):
            agent = build_agent()
            result = agent.invoke(
                {"messages": [HumanMessage(content="search for something")]},
                config={"recursion_limit": 25},
            )

        assert len(result["messages"][-1].content) > 0
```

---

## Task 9: Add pytest configuration

**Objective:** Add pytest options to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

---

## Final File Structure

```
tests/
├── conftest.py           # shared fixtures (NEW)
├── agent_test_utils.py   # mock helpers (NEW)
├── test_tools.py         # converted to pytest (MODIFIED)
└── test_agent.py         # integration tests (NEW)
```

---

## Verification

```bash
# Run all tests
pytest tests/ -v

# Run only agent tests
pytest tests/test_agent.py -v

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=research_summarizer --cov-report=term
```

---

## Pitfalls Discovered During Implementation

1. **Pydantic `StructuredTool` blocks patching `.invoke`** — LangChain tools are Pydantic v2 models with strict `__setattr__`. Neither `mocker.patch("module.tool.invoke")` nor `patch.object(tool, "invoke")` works. **Fix:** patch `_run` instead — `patch.object(tool, "_run", return_value=...)`. The `invoke` method converts dict args to kwargs before calling `_run`, so assertions must use kwargs: `mock.assert_called_once_with(query="...")`.

2. **Relative imports need `tests/__init__.py`** — when test modules import from each other (e.g., `from .agent_test_utils import ...`), the `tests/` directory must be a Python package (have `__init__.py`).

3. **`ChatOpenAI.invoke` patching requires real env vars for `_build_model()`** — even though `invoke` is mocked, `_build_model()` still reads `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` from env. Tests need a `.env` file or these set in the environment.
