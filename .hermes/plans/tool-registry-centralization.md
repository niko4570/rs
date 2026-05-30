# Centralized Tool Registry — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace hardcoded tool list in `build_agent()` with a centralized registry (`_TOOL_REGISTRY` + `get_tools()`) so adding or removing tools is a one-line change, and tests can easily swap tools.

**Architecture:** A module-level `_TOOL_REGISTRY` list holds all active tools. `get_tools()` returns a copy (safe for mutation). `build_agent(tools=None)` accepts an optional override — defaults to `get_tools()` in production, accepts custom lists in tests. Tests import the registry directly to verify all tools are registered and functional.

**Tech Stack:** Python, LangChain `create_agent`

---

## Current State (the problem)

```python
# agent.py — tools hardcoded inside build_agent()
def build_agent():
    return create_agent(
        model=_build_model(),
        tools=[search_web, fetch_url, read_text_file],  # <-- hardcoded
        system_prompt=SYSTEM_PROMPT,
    )
```

Problems:
- Adding a 4th tool requires editing `build_agent()` — mixing concerns
- Tests can't easily swap tools without patching
- No single source of truth for "what tools does this agent have?"
- `run_agent()` also can't control tools without refactoring

---

## Target State

```python
# agent.py

# === Tool Registry ===
_TOOL_REGISTRY: list = [search_web, fetch_url, read_text_file]


def get_tools() -> list:
    """Return a copy of the current tool list.

    Returns a shallow copy so callers can mutate without affecting the registry.
    """
    return list(_TOOL_REGISTRY)


def build_agent(tools=None):
    """Create the LangChain research summarizer agent.

    Args:
        tools: Override tool list (defaults to get_tools()). Useful for testing.
    """
    if tools is None:
        tools = get_tools()
    return create_agent(
        model=_build_model(),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        name="research_summarizer",
    )
```

Benefits:
- **Add a tool**: `_TOOL_REGISTRY.append(new_tool)` — one line
- **Remove a tool**: `_TOOL_REGISTRY.remove(old_tool)` — one line
- **Test with custom tools**: `build_agent(tools=[mock_tool])` — no patching
- **Inspect registry**: `from research_summarizer.agent import _TOOL_REGISTRY`
- **Single source of truth**: the list IS the registry

---

## Task 1: Extract tool registry + get_tools()

**Objective:** Move the tool list out of `build_agent()` into a module-level registry with a factory function.

**Files:**
- Modify: `research_summarizer/agent.py`

**Step 1: Add registry and factory**

Insert after the `read_text_file` tool definition, before `_build_model`:

```python
# === Tool Registry ===
# Centralized list of all tools the agent can use.
# Add new tools here — they'll be picked up automatically.
_TOOL_REGISTRY: list = [search_web, fetch_url, read_text_file]


def get_tools() -> list:
    """Return a shallow copy of the current tool list.

    Copying prevents callers from accidentally mutating the registry.
    """
    return list(_TOOL_REGISTRY)
```

**Step 2: Update `build_agent()`**

```python
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
```

**Step 3: Update `run_agent()` to pass tools through**

```python
def run_agent(request: str, tools=None) -> str:
    """Run the agent and return the final response text.

    Args:
        request: The user's research query.
        tools: Optional tool list override (passed to build_agent).
    """
    _fetch_cache.clear()
    agent = build_agent(tools=tools)
    ...
```

**Verification:**
```bash
cd /home/niko/workspace/rs && .venv/bin/python -c "
from research_summarizer.agent import _TOOL_REGISTRY, get_tools, build_agent
tools = get_tools()
print(f'Registry: {len(_TOOL_REGISTRY)} tools')
print(f'get_tools(): {len(tools)} tools')
print(f'Registry is list copy: {_TOOL_REGISTRY is not tools}')
agent = build_agent()
print(f'Agent created successfully')
# Verify custom tools work
agent2 = build_agent(tools=tools[:1])
print(f'Agent with 1 tool created successfully')
"
```

---

## Task 2: Export registry from `__init__.py`

**Objective:** Make `_TOOL_REGISTRY` and `get_tools` importable from the package root.

**Files:**
- Modify: `research_summarizer/__init__.py`

**Changes:**

```python
from research_summarizer.agent import (
    _TOOL_REGISTRY,
    build_agent,
    get_tools,
    run_agent,
)

__all__ = ["build_agent", "run_agent", "get_tools", "_TOOL_REGISTRY"]
```

**Verification:**
```bash
.venv/bin/python -c "from research_summarizer import _TOOL_REGISTRY, get_tools; print(len(_TOOL_REGISTRY))"
```

---

## Task 3: Update CLI to optionally accept tool override

**Objective:** `run_agent()` already accepts `tools=None`. The CLI doesn't need to change, but make sure it still works.

**Files:**
- Verify: `research_summarizer/cli.py` (no changes needed if it calls `run_agent(request)`)

**Verification:**
```bash
# Smoke test — CLI still works
.venv/bin/python -m research_summarizer.cli "test" 2>&1 | head -5
# Should show agent output or API error, not an import error
```

---

## Task 4: Add test for tool registry

**Objective:** Verify the registry contains the expected tools and `get_tools()` returns a copy.

**Files:**
- Modify: `tests/test_tools.py` (or `tests/test_agent.py` if it exists)

**New test:**

```python
from research_summarizer.agent import _TOOL_REGISTRY, get_tools


def test_tool_registry_contains_expected_tools():
    """The registry should contain search_web, fetch_url, read_text_file."""
    tool_names = [t.name for t in _TOOL_REGISTRY]
    assert "search_web" in tool_names
    assert "fetch_url" in tool_names
    assert "read_text_file" in tool_names


def test_get_tools_returns_copy():
    """get_tools() should return a copy, not the same list object."""
    tools = get_tools()
    assert tools == _TOOL_REGISTRY
    assert tools is not _TOOL_REGISTRY  # different object
    tools.append("fake")                # mutate copy
    assert "fake" not in _TOOL_REGISTRY  # registry unchanged


def test_build_agent_uses_registry_by_default():
    """build_agent() with no args should use get_tools()."""
    agent = build_agent()
    # Agent should exist and have tools
    assert agent is not None


def test_build_agent_accepts_custom_tools():
    """build_agent(tools=[...]) should use the provided list."""
    from research_summarizer.agent import search_web

    agent = build_agent(tools=[search_web])
    assert agent is not None
```

---

## Task 5: Update existing tests to use `build_agent(tools=...)` 

**Objective:** Any test that currently patches tool behavior should use the explicit `tools=` parameter instead of relying on the registry.

**Files:**
- Modify: `tests/test_agent.py` (if exists, or wherever agent tests live)

**Before (patch-based):**
```python
with patch.object(ChatOpenAI, 'invoke', ...):
    agent = build_agent()  # uses all 3 tools from registry
```

**After (explicit):**
```python
with patch.object(ChatOpenAI, 'invoke', ...):
    agent = build_agent(tools=[search_web, fetch_url])  # explicit
```

This is cleaner because tests declare exactly which tools they need.

---

## Task 6: Commit

```bash
git add research_summarizer/agent.py research_summarizer/__init__.py tests/
git commit -m "refactor: centralize tool registry with get_tools() factory"
```

---

## Future: Adding a 4th tool (now trivial)

After this refactor, adding a new tool is:

```python
# 1. Define the tool somewhere (agent.py or a new tools.py)
@tool
def new_research_tool(param: str) -> str:
    ...

# 2. Register it — ONE LINE
_TOOL_REGISTRY.append(new_research_tool)

# Done. build_agent() picks it up automatically.
```

---

## Verification

```bash
# Existing tests still pass
python -m unittest discover tests

# Registry-specific tests
python -m unittest tests.test_agent.TestToolRegistry  # or pytest equivalent

# CLI still works
research-agent "test query"
```
