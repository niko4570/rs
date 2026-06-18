"""Executor that runs research steps directly.

For deterministic actions (fetch a known URL, read a known file),
calls the tool function directly — no LLM involvement.
"""

from __future__ import annotations

from research_summarizer.models import ResearchStep, RunState, StepResult


def execute_step(step: ResearchStep, state: RunState) -> StepResult:
    """Execute a single research step and record the outcome in RunState.

    Calls the appropriate tool directly based on step.action.
    No LLM is involved in tool dispatch — the plan tells us what to do.

    Note: tool imports are lazy to avoid circular imports with agent.py.
    """
    # Lazy imports to avoid circular dependency with agent.py
    from research_summarizer.agent import _normalize_url, fetch_url, read_text_file, search_web

    try:
        if step.action == "search":
            content = search_web.invoke({"query": step.input})
            _record_search_urls(content, state)
            if "No search results found" in content:
                return StepResult(
                    step=step,
                    content=content,
                    failed=True,
                    retryable=True,
                    error_type="no_results",
                )
            return StepResult(step=step, content=content)

        elif step.action == "fetch":
            content = fetch_url.invoke({"url": step.input})

            if "[FETCH_ERROR]" in content:
                state.failed_fetch_urls.add(step.input)
                if "HTTP 403" in content or "HTTP 401" in content:
                    error_type = "source_unavailable"
                    retryable = True
                elif "Network failure" in content:
                    error_type = "network_error"
                    retryable = True
                elif "No extractable content" in content:
                    error_type = "empty_content"
                    retryable = True
                else:
                    error_type = "source_unavailable"
                    retryable = False

                return StepResult(
                    step=step,
                    content=content,
                    failed=True,
                    retryable=retryable,
                    error_type=error_type,
                )

            state.fetched_urls.add(step.input)
            return StepResult(step=step, content=content)

        elif step.action == "read_file":
            content = read_text_file.invoke({"path": step.input})

            if "File not found" in content:
                return StepResult(
                    step=step,
                    content=content,
                    failed=True,
                    retryable=False,
                    error_type="file_not_found",
                )

            state.read_files.add(step.input)
            return StepResult(step=step, content=content)

        else:
            return StepResult(
                step=step,
                content=f"Unknown action: {step.action}",
                failed=True,
                retryable=False,
                error_type="unknown_action",
            )

    except Exception as exc:
        return StepResult(
            step=step,
            content=f"Step execution error: {exc}",
            failed=True,
            retryable=False,
            error_type="execution_error",
        )


def _record_search_urls(search_output: str, state: RunState) -> None:
    """Extract URLs from search output and record them in RunState."""
    import re

    urls = re.findall(r"URL: (https?://\S+)", search_output)
    for url in urls:
        state.searched_urls.add(url)
