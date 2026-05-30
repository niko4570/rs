"""Integration tests for the LangChain research summarizer agent.

Tests tool selection, multi-step flow, output format, and error handling
by mocking the LLM via ChatOpenAI.invoke.
"""

from unittest.mock import patch

from langchain_core.messages import HumanMessage

from research_summarizer.agent import build_agent, fetch_url, search_web
from .agent_test_utils import make_final_msg, make_tool_call_msg, mock_agent_llm


# ---------------------------------------------------------------------------
# Tool selection
# ---------------------------------------------------------------------------


class TestAgentToolSelection:
    """Verify the agent picks the correct tool based on user input."""

    def test_topic_query_calls_search_web(self):
        """A broad topic query should trigger search_web."""
        with patch.object(
            search_web, "_run", return_value="Title: AI News\nURL: https://example.com\nSnippet: ..."
        ) as mock_search:
            with mock_agent_llm([
                make_tool_call_msg("search_web", {"query": "latest AI breakthroughs"}),
                make_final_msg("Summary: ...\nSources: example.com\nCaveats: ..."),
            ]):
                agent = build_agent()
                result = agent.invoke(
                    {"messages": [HumanMessage(content="summarize latest AI breakthroughs")]},
                    config={"recursion_limit": 25},
                )

        mock_search.assert_called_once_with(query="latest AI breakthroughs")
        assert "example.com" in result["messages"][-1].content

    def test_url_input_calls_fetch_url(self):
        """A URL input should trigger fetch_url, not search_web."""
        with patch.object(
            fetch_url,
            "_run",
            return_value="Title: Article\nURL: https://example.com/article\nText: Content here.",
        ) as mock_fetch:
            with mock_agent_llm([
                make_tool_call_msg("fetch_url", {"url": "https://example.com/article"}),
                make_final_msg("Summary: ...\nSources: example.com/article\nCaveats: ..."),
            ]):
                agent = build_agent()
                result = agent.invoke(
                    {"messages": [HumanMessage(content="https://example.com/article")]},
                    config={"recursion_limit": 25},
                )

        mock_fetch.assert_called_once_with(url="https://example.com/article")


# ---------------------------------------------------------------------------
# Multi-step flow
# ---------------------------------------------------------------------------


class TestAgentMultiStepFlow:
    """Verify the agent chains multiple tool calls correctly."""

    def test_search_then_fetch_flow(self):
        """Agent should search, then fetch top results, then summarize."""
        with patch.object(
            search_web,
            "_run",
            return_value=(
                "Title: Article 1\nURL: https://a.com/1\nSnippet: ...\n\n"
                "Title: Article 2\nURL: https://a.com/2\nSnippet: ..."
            ),
        ) as mock_search:
            with patch.object(
                fetch_url,
                "_run",
                side_effect=[
                    "Title: A1\nURL: https://a.com/1\nText: Content one.",
                    "Title: A2\nURL: https://a.com/2\nText: Content two.",
                ],
            ) as mock_fetch:
                with mock_agent_llm([
                    make_tool_call_msg("search_web", {"query": "climate change 2025"}, call_id="c1"),
                    make_tool_call_msg("fetch_url", {"url": "https://a.com/1"}, call_id="c2"),
                    make_tool_call_msg("fetch_url", {"url": "https://a.com/2"}, call_id="c3"),
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


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestAgentOutputFormat:
    """Verify the agent produces properly formatted final output."""

    def test_output_has_required_sections(self):
        """Final answer should include Summary, Sources, Caveats."""
        with patch.object(
            search_web, "_run", return_value="Title: T\nURL: https://x.com\nSnippet: ..."
        ):
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

    def test_mentions_caveats_when_no_results(self):
        """When search returns nothing, agent should note it in caveats."""
        with patch.object(
            search_web, "_run", return_value="No search results found."
        ):
            with mock_agent_llm([
                make_tool_call_msg("search_web", {"query": "nonexistent topic xyz123"}, call_id="c1"),
                make_final_msg(
                    "Summary: No results found.\n"
                    "Sources: none\n"
                    "Caveats: Search returned no results."
                ),
            ]):
                agent = build_agent()
                result = agent.invoke(
                    {"messages": [HumanMessage(content="research nonexistent topic xyz123")]},
                    config={"recursion_limit": 25},
                )

        final = result["messages"][-1].content
        assert "no results" in final.lower() or "Caveats" in final


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestAgentErrorHandling:
    """Verify the agent handles tool errors without crashing."""

    def test_handles_fetch_error(self):
        """Agent should continue when fetch_url returns [FETCH_ERROR]."""
        with patch.object(
            fetch_url, "_run", return_value="[FETCH_ERROR] Source unavailable: HTTP 403"
        ):
            with mock_agent_llm([
                make_tool_call_msg("fetch_url", {"url": "https://paywall.com"}, call_id="c1"),
                make_final_msg(
                    "Summary: Could not access source.\n"
                    "Sources: paywall.com (inaccessible)\n"
                    "Caveats: Source was behind paywall."
                ),
            ]):
                agent = build_agent()
                result = agent.invoke(
                    {"messages": [HumanMessage(content="https://paywall.com")]},
                    config={"recursion_limit": 25},
                )

        final = result["messages"][-1].content
        assert len(final) > 0

    def test_handles_search_error(self):
        """Agent should handle missing API key gracefully."""
        with patch.object(
            search_web, "_run", return_value="Search failed: missing SERPAPI_API_KEY"
        ):
            with mock_agent_llm([
                make_tool_call_msg("search_web", {"query": "test"}, call_id="c1"),
                make_final_msg(
                    "Summary: Cannot search \u2014 API key missing.\n"
                    "Sources: none\n"
                    "Caveats: API configuration issue."
                ),
            ]):
                agent = build_agent()
                result = agent.invoke(
                    {"messages": [HumanMessage(content="search for something")]},
                    config={"recursion_limit": 25},
                )

        assert len(result["messages"][-1].content) > 0
