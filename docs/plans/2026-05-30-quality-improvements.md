# Plan: Error Markers, Trafilatura, and Path Fix

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Three independent quality-of-life improvements to the research summarizer agent: (1) distinct error markers so the model never confuses fetch failures with content, (2) trafilatura replacing BeautifulSoup for real content extraction, (3) read_text_file path logic that doesn't break when cwd != project root.

**Architecture:** Each change is self-contained and touches different parts of `agent.py` + `pyproject.toml` + `tests/test_tools.py`. Because they're independent, we use `git worktree` to develop all three in parallel on separate branches, then merge sequentially.

**Tech Stack:** Python 3.11+, LangChain, trafilatura, SerpApi, unittest

---

## Git Worktree Strategy

Three features, three branches, three worktrees — developed in parallel, merged one at a time.

```
main repo:     /home/niko/workspace/rs              (main branch)
worktree 1:    /home/niko/workspace/rs-error-markers (feat/error-markers)
worktree 2:    /home/niko/workspace/rs-trafilatura   (feat/trafilatura)
worktree 3:    /home/niko/workspace/rs-path-fix      (feat/path-fix)
```

Each worktree is an independent checkout — you can run tests, edit files, and commit in all three simultaneously without conflicts because they touch different code regions. After all three pass, merge back to main one by one.

**Merge order:** path-fix → error-markers → trafilatura (trafilatura last because it has a dependency change).

---

### Task 0: Create worktrees and branches

**Objective:** Set up the parallel development environment.

**Step 1: Create the three feature branches from main**

```bash
cd /home/niko/workspace/rs
git branch feat/error-markers main
git branch feat/trafilatura main
git branch feat/path-fix main
```

**Step 2: Create worktrees**

```bash
git worktree add ../rs-error-markers feat/error-markers
git worktree add ../rs-trafilatura feat/trafilatura
git worktree add ../rs-path-fix feat/path-fix
```

**Step 3: Verify worktrees exist**

```bash
git worktree list
```

Expected: 4 entries (main + 3 feature worktrees).

**Step 4: Install deps in each worktree**

```bash
# In each worktree:
cd /home/niko/workspace/rs-error-markers && python -m venv .venv && source .venv/bin/activate && pip install -e .
cd /home/niko/workspace/rs-trafilatura && python -m venv .venv && source .venv/bin/activate && pip install -e .
cd /home/niko/workspace/rs-path-fix && python -m venv .venv && source .venv/bin/activate && pip install -e .
```

---

## Feature A: Error Markers (worktree: rs-error-markers, branch: feat/error-markers)

### Task A1: Add [FETCH_ERROR] prefix to fetch_url error returns

**Objective:** Ensure the LLM never confuses fetch errors with article content.

**Files:**
- Modify: `research_summarizer/agent.py` (lines 133, 135)
- Modify: `tests/test_tools.py` (lines 187, 196)

**Step 1: Update agent.py error returns**

In `research_summarizer/agent.py`, change two return statements inside `fetch_url`:

```python
# Line 133 — HTTP error: change from
return f"FETCH ERROR (source unavailable): HTTP {exc.response.status_code}"
# to
return f"[FETCH_ERROR] Source unavailable: HTTP {exc.response.status_code}"

# Line 135 — network error: change from
return f"URL fetch failed (network): {exc}"
# to
return f"[FETCH_ERROR] Network failure: {exc}"
```

**Step 2: Update tests to expect new format**

In `tests/test_tools.py`:

```python
# test_http_error_returns_error_text (line 186-188): change
self.assertIn("FETCH ERROR (source unavailable)", result)
# to
self.assertIn("[FETCH_ERROR] Source unavailable", result)

# test_network_error_returns_error_text (line 195-197): change
self.assertIn("URL fetch failed (network)", result)
# to
self.assertIn("[FETCH_ERROR] Network failure", result)
```

**Step 3: Add system prompt instruction**

In `research_summarizer/agent.py`, add to `SYSTEM_PROMPT` after "Do not invent citations...":

```
- If a fetch returns `[FETCH_ERROR]`, treat that source as unavailable. Do not cite it or use its content.
```

**Step 4: Run tests**

```bash
cd /home/niko/workspace/rs-error-markers
source .venv/bin/activate
python -m unittest discover tests -v
```

Expected: all existing tests pass with updated assertions.

**Step 5: Verify error format is distinctive**

Quick manual check — the prefix `[FETCH_ERROR]` should never appear in legitimate page content. It's bracketed, uppercase with underscore — unambiguous.

**Step 6: Commit**

```bash
git add research_summarizer/agent.py tests/test_tools.py
git commit -m "feat: add [FETCH_ERROR] prefix so model never confuses errors with content"
```

---

## Feature B: Trafilatura replacing BeautifulSoup (worktree: rs-trafilatura, branch: feat/trafilatura)

### Task B1: Add trafilatura dependency

**Objective:** Add trafilatura to the project.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependency**

In `pyproject.toml`, add to the `dependencies` list:

```toml
"trafilatura>=2.0.0",
```

**Step 2: Install**

```bash
cd /home/niko/workspace/rs-trafilatura
source .venv/bin/activate
pip install -e .
```

Verify: `python -c "import trafilatura; print(trafilatura.__version__)"`

### Task B2: Rewrite fetch_url to use trafilatura

**Objective:** Replace BeautifulSoup extraction with trafilatura for cleaner, smaller extracted text.

**Files:**
- Modify: `research_summarizer/agent.py` (imports + fetch_url function)

**Step 1: Update imports**

In `research_summarizer/agent.py`:

```python
# Remove:
from bs4 import BeautifulSoup

# Add:
import trafilatura
```

Also remove `bs4` from pyproject.toml if it's no longer needed elsewhere (it isn't — search_web uses SerpApi SDK, read_text_file uses Path.read_text).

**Step 2: Rewrite fetch_url content extraction**

Replace the BeautifulSoup section (lines 137-143) with trafilatura. The new `fetch_url` body after the HTTP request:

```python
    downloaded = response.text

    # trafilatura extracts main content, discards nav/ads/boilerplate
    body = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        output_format="txt",
    )

    if not body:
        return "[FETCH_ERROR] No extractable content from this page."

    # Get title from trafilatura metadata or fall back to URL
    metadata = trafilatura.extract(downloaded, output_format="txt", include_comments=False, include_tables=False, no_fallback=False)
    # Actually, trafilatura can return metadata separately:
    meta = trafilatura.bare_extraction(downloaded, include_comments=False, include_tables=False, no_fallback=False)
    title = meta.get("title") if meta and meta.get("title") else url

    body_clean = _clean_text(body, 8000)
    result = f"Title: {title}\nURL: {url}\nText: {body_clean}"

    _fetch_cache[normalized] = result
    return result
```

Wait — `bare_extraction` may not exist in older trafilatura. Let me check the API. The standard approach:

```python
    downloaded = response.text

    # Extract main text content
    body = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )

    if not body:
        return "[FETCH_ERROR] No extractable content from this page."

    # Extract metadata for title
    metadata = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
        output_format="xml",
    )
    # Parse title from XML metadata if present
    title = url
    if metadata:
        from xml.etree import ElementTree
        try:
            root = ElementTree.fromstring(metadata)
            title_el = root.find(".//title") if root is not None else None
            if title_el is not None and title_el.text:
                title = title_el.text
        except ElementTree.ParseError:
            pass

    body_clean = _clean_text(body, 8000)
    result = f"Title: {title}\nURL: {url}\nText: {body_clean}"

    _fetch_cache[normalized] = result
    return result
```

Hmm, this is getting complex. Simpler approach: use trafilatura for body, keep requests + simple regex for title extraction from raw HTML `<title>` tag. trafilatura is for the content, not the title.

```python
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
```

This keeps it simple. No BeautifulSoup, no XML parsing. trafilatura for the heavy lifting, regex for the title tag.

**Step 3: Remove bs4 from dependencies**

In `pyproject.toml`, remove:
```toml
"beautifulsoup4>=4.12.3",
```

### Task B3: Update tests for trafilatura

**Objective:** Fix tests that mock BeautifulSoup or expect BeautifulSoup-processed output.

**Files:**
- Modify: `tests/test_tools.py` (FetchUrlTests class)

The existing tests mock `requests.get` and check output. With trafilatura, the content extraction path changes — we no longer rely on BeautifulSoup, so those mocks stay the same (we mock requests, not the parser). But we need to adjust the mock response text to include valid HTML that trafilatura can extract from.

**Step 1: Update `test_returns_page_text`**

trafilatura needs enough HTML to extract meaningful content. The current mock text `<html><head><title>Test Page</title></head><body><p>Hello world.</p></body></html>` should work — trafilatura extracts `<p>` content. This test should still pass.

**Step 2: Update `test_caches_duplicate_url`**

Same — trafilatura should extract "Content" from `<body>Content</body>`. Should still pass.

**Step 3: Update `test_http_error_not_cached`**

This test doesn't depend on content extraction — it checks error handling. Should still pass.

**Step 4: Run tests**

```bash
cd /home/niko/workspace/rs-trafilatura
source .venv/bin/activate
python -m unittest discover tests -v
```

Expected: all FetchUrlTests pass.

**Step 5: Commit**

```bash
git add pyproject.toml research_summarizer/agent.py tests/test_tools.py
git commit -m "feat: replace BeautifulSoup with trafilatura for content extraction"
```

---

## Feature C: Fix read_text_file path restriction (worktree: rs-path-fix, branch: feat/path-fix)

### Task C1: Add a project-root concept to read_text_file

**Objective:** Make `read_text_file` resolve paths relative to a stable project root instead of fragile `cwd`.

**Files:**
- Modify: `research_summarizer/agent.py` (read_text_file function)
- Modify: `tests/test_tools.py` (ReadTextFileTests class)

**Step 1: Define project root resolution**

The cleanest approach: resolve relative to the directory containing `agent.py`. This is stable regardless of where the user runs the CLI from.

In `research_summarizer/agent.py`, at module level:

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
```

This gives `/home/niko/workspace/rs` regardless of cwd.

**Step 2: Update read_text_file**

Change the function:

```python
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
```

Key changes:
- No longer depends on `Path.cwd()`
- Relative paths resolved against `_PROJECT_ROOT` (the repo root)
- Security check uses `relative_to()` which is cleaner and handles symlinks correctly

**Step 3: Update tests**

In `tests/test_tools.py`, the `ReadTextFileTests` class currently patches `Path.cwd`. With the new approach, we need a different strategy.

The test `test_reads_project_file` creates a temporary directory and a file inside it. We need to make `_PROJECT_ROOT` point to that temp dir for the test.

Option: patch `_PROJECT_ROOT` directly:

```python
class ReadTextFileTests(unittest.TestCase):
    def test_reads_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("Research notes about LangChain.", encoding="utf-8")

            with patch("research_summarizer.agent._PROJECT_ROOT", root.resolve()):
                result = read_text_file.invoke({"path": str(source)})

            self.assertIn("Research notes about LangChain.", result)

    def test_refuses_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with patch("research_summarizer.agent._PROJECT_ROOT", root.resolve()):
                result = read_text_file.invoke({"path": "/etc/passwd"})

            self.assertIn("Refusing to read outside", result)

    def test_resolves_relative_paths(self):
        """Relative paths should resolve against _PROJECT_ROOT."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "notes.md"
            source.write_text("Relative path content.", encoding="utf-8")

            with patch("research_summarizer.agent._PROJECT_ROOT", root.resolve()):
                result = read_text_file.invoke({"path": "notes.md"})

            self.assertIn("Relative path content.", result)
```

Remove the `from pathlib import Path` import if cwd patching was the only use, but it's still needed for tests — keep it.

**Step 4: Run tests**

```bash
cd /home/niko/workspace/rs-path-fix
source .venv/bin/activate
python -m unittest discover tests -v
```

Expected: all 3 ReadTextFileTests pass.

**Step 5: Commit**

```bash
git add research_summarizer/agent.py tests/test_tools.py
git commit -m "fix: resolve read_text_file paths against project root, not cwd"
```

---

## Merge and Integration

### Task D1: Merge all three branches back to main

**Objective:** Bring all three features into main, in order of least to most likely to conflict.

**Step 1: Merge path-fix (simplest, standalone function change)**

```bash
cd /home/niko/workspace/rs
git merge feat/path-fix
```

**Step 2: Merge error-markers (touches same file but different lines)**

```bash
git merge feat/error-markers
```

May have a trivial conflict if path-fix and error-markers both touched `agent.py` imports or nearby lines. Resolve manually — they're in different functions.

**Step 3: Merge trafilatura (dependency change, last to catch any breakage)**

```bash
git merge feat/trafilatura
```

Reinstall after dependency change:

```bash
source .venv/bin/activate && pip install -e .
```

**Step 4: Run full test suite on main**

```bash
cd /home/niko/workspace/rs
source .venv/bin/activate
python -m unittest discover tests -v
```

Expected: all tests pass (ReadTextFileTests, SearchWebTests, UrlNormalizationTests, FetchUrlTests).

### Task D2: Clean up worktrees

```bash
cd /home/niko/workspace/rs
git worktree remove ../rs-error-markers
git worktree remove ../rs-trafilatura
git worktree remove ../rs-path-fix
git branch -d feat/error-markers feat/trafilatura feat/path-fix
```

### Task D3: Commit the plan and AGENTS.md

```bash
git add docs/plans/2026-05-30-quality-improvements.md AGENTS.md
git commit -m "docs: add implementation plan for error markers, trafilatura, and path fix"
```

---

## Verification Checklist

After all merges, verify on main:

- [ ] `python -m unittest discover tests -v` — all tests pass
- [ ] `pip install -e .` installs without errors
- [ ] `python -c "from research_summarizer.agent import build_agent; print('imports OK')"` — no import errors
- [ ] `python -c "import trafilatura; print('trafilatura OK')"` — trafilatura installed
- [ ] `python -c "import bs4"` fails — BeautifulSoup removed
- [ ] `git worktree list` shows only main
- [ ] SearchWebTests, UrlNormalizationTests unchanged and still pass
