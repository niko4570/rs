"""Tests for Phase 2: explicit agent loop — planner, executor, and loop."""

import json
from unittest.mock import Mock, patch

import pytest

from research_summarizer.agent import run_agent
from research_summarizer.executor import execute_step
from research_summarizer.models import ResearchPlan, ResearchStep, RunState, StepResult
from research_summarizer.planner import plan_research


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_model(content: str):
    """Create a mock ChatOpenAI that returns the given content."""
    model = Mock()
    response = Mock()
    response.content = content
    model.invoke.return_value = response
    return model


def _plan_json(steps: list[dict]) -> str:
    return json.dumps({
        "steps": steps,
        "comparison_strategy": "cross-check sources",
    })


def _critique_json(score: float = 0.85, should_revise: bool = False) -> str:
    return json.dumps({
        "source_fidelity": score,
        "source_diversity": score,
        "caveat_specificity": score,
        "completeness": score,
        "overall_score": score,
        "gaps": [],
        "should_revise": should_revise,
    })


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------


class TestPlanner:
    """Tests for plan_research — LLM generates a plan, code parses it."""

    def test_url_request_creates_fetch_step(self):
        model = _mock_model(_plan_json([
            {"action": "fetch", "input": "https://example.com/article", "purpose": "get article text"},
        ]))
        plan = plan_research("https://example.com/article", model)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "fetch"
        assert plan.steps[0].input == "https://example.com/article"

    def test_file_request_creates_read_step(self):
        model = _mock_model(_plan_json([
            {"action": "read_file", "input": "README.md", "purpose": "read local docs"},
        ]))
        plan = plan_research("Summarize README.md", model)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "read_file"

    def test_topic_request_creates_search_steps(self):
        model = _mock_model(_plan_json([
            {"action": "search", "input": "AI regulation China 2026", "purpose": "find recent news"},
            {"action": "search", "input": "China AI policy latest", "purpose": "broader context"},
        ]))
        plan = plan_research("latest AI regulation in China", model)
        assert len(plan.steps) == 2
        assert all(s.action == "search" for s in plan.steps)

    def test_empty_steps_raises(self):
        model = _mock_model(_plan_json([]))
        with pytest.raises(ValueError, match="no steps"):
            plan_research("something", model)


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------


class TestExecutor:
    """Tests for execute_step — code calls tools directly, no LLM."""

    def test_fetch_success_records_url(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["fetch_url"]),
            "fetch_url",
        ) as mock_tool:
            mock_tool.invoke.return_value = "Title: T\nURL: https://x.com\nText: content"
            result = execute_step(
                ResearchStep(action="fetch", input="https://x.com", purpose="test"),
                state,
            )
        assert result.failed is False
        assert "https://x.com" in state.fetched_urls

    def test_fetch_403_records_failure(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["fetch_url"]),
            "fetch_url",
        ) as mock_tool:
            mock_tool.invoke.return_value = "[FETCH_ERROR] Source unavailable: HTTP 403"
            result = execute_step(
                ResearchStep(action="fetch", input="https://paywall.com", purpose="test"),
                state,
            )
        assert result.failed is True
        assert result.retryable is True
        assert result.error_type == "source_unavailable"
        assert "https://paywall.com" in state.failed_fetch_urls

    def test_fetch_network_error(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["fetch_url"]),
            "fetch_url",
        ) as mock_tool:
            mock_tool.invoke.return_value = "[FETCH_ERROR] Network failure: timeout"
            result = execute_step(
                ResearchStep(action="fetch", input="https://down.com", purpose="test"),
                state,
            )
        assert result.failed is True
        assert result.error_type == "network_error"

    def test_search_records_urls(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["search_web"]),
            "search_web",
        ) as mock_tool:
            mock_tool.invoke.return_value = (
                "Title: Result 1\nURL: https://a.com\nSnippet: ...\n\n"
                "Title: Result 2\nURL: https://b.com\nSnippet: ..."
            )
            result = execute_step(
                ResearchStep(action="search", input="test query", purpose="test"),
                state,
            )
        assert result.failed is False
        assert "https://a.com" in state.searched_urls
        assert "https://b.com" in state.searched_urls

    def test_search_no_results(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["search_web"]),
            "search_web",
        ) as mock_tool:
            mock_tool.invoke.return_value = "No search results found."
            result = execute_step(
                ResearchStep(action="search", input="xyznonexistent", purpose="test"),
                state,
            )
        assert result.failed is True
        assert result.retryable is True
        assert result.error_type == "no_results"

    def test_read_file_success(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["read_text_file"]),
            "read_text_file",
        ) as mock_tool:
            mock_tool.invoke.return_value = "File content here."
            result = execute_step(
                ResearchStep(action="read_file", input="notes.md", purpose="test"),
                state,
            )
        assert result.failed is False
        assert "notes.md" in state.read_files

    def test_read_file_not_found(self):
        state = RunState()
        with patch.object(
            __import__("research_summarizer.agent", fromlist=["read_text_file"]),
            "read_text_file",
        ) as mock_tool:
            mock_tool.invoke.return_value = "File not found: missing.txt"
            result = execute_step(
                ResearchStep(action="read_file", input="missing.txt", purpose="test"),
                state,
            )
        assert result.failed is True
        assert not result.retryable


# ---------------------------------------------------------------------------
# Explicit loop (run_agent) integration tests
# ---------------------------------------------------------------------------


class TestExplicitLoop:
    """Tests for the full explicit loop — plan → execute → summarize → parse → validate."""

    _SUMMARY_JSON = json.dumps({
        "summary_bullets": ["Point 1", "Point 2", "Point 3", "Point 4"],
        "key_details": "Some facts.",
        "sources": [{"title": "Source", "url": "https://alt.com"}],
        "caveats": ["Limited to one source"],
    })

    def test_full_pipeline(self):
        """End-to-end: topic → search → fetch → summarize → parse → result."""
        # Plan: search, then fetch
        plan_text = _plan_json([
            {"action": "search", "input": "test topic", "purpose": "find info"},
            {"action": "fetch", "input": "https://fetched.com", "purpose": "get details"},
        ])

        summary_json = json.dumps({
            "summary_bullets": ["Point 1", "Point 2", "Point 3", "Point 4"],
            "key_details": "Some facts.",
            "sources": [{"title": "Source", "url": "https://fetched.com"}],
            "caveats": ["Limited to one source"],
        })

        model = Mock()
        model.invoke.side_effect = [
            Mock(content=plan_text),           # plan
            Mock(content="draft summary"),      # summarize
            Mock(content=summary_json),         # parse
            Mock(content=_critique_json()),     # critique
        ]

        with patch.object(
            __import__("research_summarizer.agent", fromlist=["search_web"]),
            "search_web",
        ) as mock_search:
            mock_search.invoke.return_value = "Title: R\nURL: https://fetched.com\nSnippet: ..."

            with patch.object(
                __import__("research_summarizer.agent", fromlist=["fetch_url"]),
                "fetch_url",
            ) as mock_fetch:
                mock_fetch.invoke.return_value = "Title: Source\nURL: https://fetched.com\nText: content"

                with patch(
                    "research_summarizer.agent._build_model",
                    return_value=model,
                ):
                    result = run_agent("research test topic")

        assert len(result.summary_bullets) == 4
        assert result.sources[0].url == "https://fetched.com"
        mock_search.invoke.assert_called_once()
        mock_fetch.invoke.assert_called_once()

    def test_replans_on_failed_fetch(self):
        """When fetch fails with 403, replan generates a new search step."""
        plan_text = _plan_json([
            {"action": "search", "input": "topic", "purpose": "find"},
            {"action": "fetch", "input": "https://paywall.com", "purpose": "get"},
        ])

        replacement_json = json.dumps({
            "action": "search",
            "input": "topic alternative source",
            "purpose": "find non-paywall version",
        })

        model = Mock()
        # Flow: plan → replan → summarize → parse → critique (all pass, no repair/revision)
        model.invoke.side_effect = [
            Mock(content=plan_text),
            Mock(content=replacement_json),
            Mock(content="draft summary"),
            Mock(content=self._SUMMARY_JSON),
            Mock(content=_critique_json()),
        ]

        with patch.object(
            __import__("research_summarizer.agent", fromlist=["search_web"]),
            "search_web",
        ) as mock_search:
            mock_search.invoke.side_effect = [
                "Title: R\nURL: https://paywall.com\nSnippet: ...",  # original search
                "Title: R2\nURL: https://alt.com\nSnippet: ...",     # replan search
            ]

            with patch.object(
                __import__("research_summarizer.agent", fromlist=["fetch_url"]),
                "fetch_url",
            ) as mock_fetch:
                mock_fetch.invoke.return_value = "[FETCH_ERROR] Source unavailable: HTTP 403"

                with patch(
                    "research_summarizer.agent._build_model",
                    return_value=model,
                ):
                    result = run_agent("research topic")

        assert mock_search.invoke.call_count == 2  # original + replan
        assert mock_fetch.invoke.call_count == 1    # original fetch only, not retried
        assert len(result.summary_bullets) == 4

    def test_replan_bounded(self):
        """Replanning stops at max_replans (3)."""
        plan_text = _plan_json([
            {"action": "fetch", "input": "https://fail.com", "purpose": "get"},
            {"action": "fetch", "input": "https://fail2.com", "purpose": "get2"},
            {"action": "fetch", "input": "https://fail3.com", "purpose": "get3"},
            {"action": "fetch", "input": "https://fail4.com", "purpose": "get4"},
            {"action": "fetch", "input": "https://fail5.com", "purpose": "get5"},
        ])

        replacement_json = json.dumps({
            "action": "search",
            "input": "alternative",
            "purpose": "find alternative",
        })

        model = Mock()
        # Flow: plan → 3 replans → summarize → parse → critique
        model.invoke.side_effect = [
            Mock(content=plan_text),
            Mock(content=replacement_json),
            Mock(content=replacement_json),
            Mock(content=replacement_json),
            Mock(content="draft summary"),
            Mock(content=self._SUMMARY_JSON),
            Mock(content=_critique_json()),
        ]

        with patch.object(
            __import__("research_summarizer.agent", fromlist=["fetch_url"]),
            "fetch_url",
        ) as mock_fetch:
            mock_fetch.invoke.return_value = "[FETCH_ERROR] Source unavailable: HTTP 403"

            with patch.object(
                __import__("research_summarizer.agent", fromlist=["search_web"]),
                "search_web",
            ) as mock_search:
                mock_search.invoke.return_value = "Title: R\nURL: https://alt.com\nSnippet: ..."

                with patch(
                    "research_summarizer.agent._build_model",
                    return_value=model,
                ):
                    result = run_agent("research")

        # Max 3 replans across all steps
        replan_calls = [c for c in model.invoke.call_args_list
                        if "replacement" in str(c).lower() or "null" in str(c).lower()]
        # 5 steps, first 4 fail, but only 3 replans allowed
        assert mock_fetch.invoke.call_count == 5   # 5 original fetches
        assert mock_search.invoke.call_count == 3  # 3 replan searches (max)
        assert len(result.summary_bullets) == 4
