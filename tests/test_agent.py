"""Tests for the minimal agent flow: dispatch -> tool -> summarize."""

import json
from unittest.mock import Mock, patch

from research_summarizer.agent import _resolve_action, run_agent
from research_summarizer.models import SummaryResult


def _summary_json(url: str = "https://example.com/article") -> str:
    return json.dumps({
        "summary_bullets": ["Point 1", "Point 2", "Point 3", "Point 4"],
        "key_details": "Some facts.",
        "sources": [{"title": "Source", "url": url}],
        "caveats": ["Limited to a single source"],
    })


def _mock_model(summary_json: str) -> Mock:
    model = Mock()
    model.invoke.return_value = Mock(content=summary_json)
    return model


# ---------------------------------------------------------------------------
# Deterministic dispatch
# ---------------------------------------------------------------------------


class TestResolveAction:
    def test_url_dispatches_to_fetch(self):
        assert _resolve_action("https://example.com/article") == ("fetch", "https://example.com/article")

    def test_url_embedded_in_instruction(self):
        assert _resolve_action("Summarize https://example.com/article") == ("fetch", "https://example.com/article")

    def test_md_file_dispatches_to_read_file(self):
        assert _resolve_action("README.md") == ("read_file", "README.md")

    def test_txt_file_dispatches_to_read_file(self):
        assert _resolve_action("Summarize notes.txt") == ("read_file", "notes.txt")

    def test_topic_dispatches_to_search(self):
        assert _resolve_action("latest AI news") == ("search", "latest AI news")


# ---------------------------------------------------------------------------
# End-to-end flows
# ---------------------------------------------------------------------------


class TestRunAgent:
    def test_url_flow_fetches_then_summarizes(self):
        model = _mock_model(_summary_json("https://example.com/article"))

        with patch("research_summarizer.agent._build_model", return_value=model), \
             patch("research_summarizer.agent.fetch_url",
                   return_value="Title: T\nURL: https://example.com/article\nText: content") as mock_fetch:
            result = run_agent("https://example.com/article")

        mock_fetch.assert_called_once_with("https://example.com/article")
        assert isinstance(result, SummaryResult)
        assert result.sources[0].url == "https://example.com/article"

    def test_file_flow_reads_then_summarizes(self):
        model = _mock_model(_summary_json())

        with patch("research_summarizer.agent._build_model", return_value=model), \
             patch("research_summarizer.agent.read_text_file",
                   return_value="File content.") as mock_read:
            result = run_agent("README.md")

        mock_read.assert_called_once_with("README.md")
        assert isinstance(result, SummaryResult)

    def test_topic_flow_searches_then_summarizes(self):
        model = _mock_model(_summary_json("https://example.com/story"))

        with patch("research_summarizer.agent._build_model", return_value=model), \
             patch("research_summarizer.agent.search_web",
                   return_value="Title: R\nURL: https://example.com/story\nSnippet: ...") as mock_search:
            result = run_agent("latest AI news")

        mock_search.assert_called_once_with("latest AI news")
        assert isinstance(result, SummaryResult)

    def test_progress_callback_invoked(self):
        model = _mock_model(_summary_json())
        stages = []

        with patch("research_summarizer.agent._build_model", return_value=model), \
             patch("research_summarizer.agent.fetch_url", return_value="content"):
            run_agent("https://example.com", on_progress=lambda stage, msg: stages.append(stage))

        assert stages[0] == "execute"
        assert "summarize" in stages
        assert stages[-1] == "done"
