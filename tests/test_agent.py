"""Tests for the minimal agent flow: dispatch -> tool -> summarize."""

import json
from unittest.mock import Mock, patch

import pytest

from research_summarizer.agent import _resolve_action, run_agent
from research_summarizer.evidence import EvidenceItem, EvidenceResult, format_evidence
from research_summarizer.models import SummaryResult
from research_summarizer.parser import ParseError


def _item(title: str, content: str, id_: str = "S1", url: str = "https://example.com/story") -> EvidenceItem:
    return EvidenceItem(id=id_, title=title, url=url, content=content)


def _evidence_result(*items: EvidenceItem) -> EvidenceResult:
    return EvidenceResult(items=tuple(items))


def _summary_json(url: str | None = None, excerpt: str | None = None) -> str:
    return json.dumps({
        "summary_bullets": ["Point 1", "Point 2", "Point 3", "Point 4"],
        "key_details": "Some facts.",
        "sources": [{"title": "Source", "url": url}] if url else [],
        "citations": [
            {"bullet_index": index, "source_url": url, "excerpt": excerpt}
            for index in range(4)
        ] if excerpt else [],
        "caveats": ["Limited to a single source"],
    })


def _mock_model(summary_json: str) -> Mock:
    model = Mock()
    bound = Mock()
    bound.invoke.return_value = Mock(content=summary_json)
    model.bind.return_value = bound
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

    def test_explicit_topic_keeps_url_and_filename_in_query(self):
        query = "Compare https://example.com/article with README.md"
        model = _mock_model(_summary_json())
        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=EvidenceResult(note="No search results found.")) as mock_search, \
             patch("research_summarizer.agent.acquire_evidence") as mock_acquire:
            run_agent(query, action="search")
        mock_search.assert_called_once_with(query)
        mock_acquire.assert_not_called()


# ---------------------------------------------------------------------------
# End-to-end flows
# ---------------------------------------------------------------------------


class TestRunAgent:
    def test_url_flow_fetches_then_summarizes(self):
        model = _mock_model(_summary_json("https://example.com/article", "content"))

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.evidence.fetch_url",
                   return_value="Title: T\nURL: https://example.com/article\nText: content") as mock_fetch:
            result = run_agent("https://example.com/article")

        mock_fetch.assert_called_once_with("https://example.com/article")
        assert isinstance(result, SummaryResult)
        assert result.sources[0].url == "https://example.com/article"

    def test_file_flow_reads_then_summarizes(self):
        model = _mock_model(_summary_json(excerpt="File content."))

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.evidence.read_text_file",
                   return_value="File content.") as mock_read:
            result = run_agent("README.md")

        mock_read.assert_called_once_with("README.md")
        assert isinstance(result, SummaryResult)
        assert result.citations[0].source_url is None
        assert result.citations[0].excerpt == "File content."

    def test_topic_flow_searches_then_summarizes(self):
        model = _mock_model(_summary_json("https://example.com/story", "..."))
        item = _item("R", "...")

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=_evidence_result(item)) as mock_search, \
             patch("research_summarizer.agent.judge_evidence",
                   return_value=_evidence_result(item)):
            result = run_agent("latest AI news")

        mock_search.assert_called_once_with("latest AI news")
        assert isinstance(result, SummaryResult)
        assert {citation.bullet_index for citation in result.citations} == set(range(4))

    def test_duplicate_search_url_can_cite_either_selected_excerpt(self):
        first = _item("First", "First passage", id_="S1")
        second = _item("Second", "Second passage", id_="S2")
        selected = _evidence_result(first, second)
        model = _mock_model(_summary_json(first.url, "First passage"))
        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items", return_value=selected), \
             patch("research_summarizer.agent.judge_evidence", return_value=selected):
            result = run_agent("topic")
        assert result.citations[0].excerpt == "First passage"

    def test_search_selected_evidence_is_passed_to_summarizer(self):
        kept = _item("Keep", "Full substantive body used for synthesis.")
        dropped = _item("Drop", "Dropped body.", id_="S2", url="https://example.com/drop")
        acquired = _evidence_result(kept, dropped)
        selected = _evidence_result(kept)

        with patch("research_summarizer.agent.build_model", return_value=Mock()), \
             patch("research_summarizer.agent.search_web_items", return_value=acquired), \
             patch("research_summarizer.agent.judge_evidence",
                   return_value=selected) as mock_judge, \
             patch("research_summarizer.agent.summarize_evidence",
                   return_value=_summary_json("https://example.com/story",
                                              "Full substantive body")) as mock_summarize:
            result = run_agent("latest AI news")

        mock_judge.assert_called_once_with("latest AI news", acquired.items)
        mock_summarize.assert_called_once()
        passed_request, passed_evidence = mock_summarize.call_args.args[:2]
        assert passed_request == "latest AI news"
        assert passed_evidence == format_evidence(selected)
        assert "Full substantive body used for synthesis." in passed_evidence
        assert "Dropped body." not in passed_evidence
        assert isinstance(result, SummaryResult)

    def test_empty_search_skips_jev_and_passes_note(self):
        model = _mock_model(_summary_json())

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=EvidenceResult(note="No search results found.")), \
             patch("research_summarizer.agent.judge_evidence") as mock_judge, \
             patch("research_summarizer.agent.summarize_evidence",
                   return_value=_summary_json()) as mock_summarize:
            run_agent("latest AI news")

        mock_judge.assert_not_called()
        assert mock_summarize.call_args.args[1] == "No search results found."

    def test_empty_file_can_return_uncertainty_without_citations(self):
        model = _mock_model(_summary_json())
        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.evidence.read_text_file", return_value=""):
            result = run_agent("README.md")
        assert result.citations == []

    def test_fetch_and_file_paths_bypass_jev(self):
        cases = (
            ("https://example.com/article", "research_summarizer.evidence.fetch_url",
             "https://example.com/article"),
            ("README.md", "research_summarizer.evidence.read_text_file", None),
        )

        for request, patch_target, url in cases:
            model = _mock_model(_summary_json(url, "content"))
            with patch("research_summarizer.agent.build_model", return_value=model), \
                 patch(patch_target, return_value="content"), \
                 patch("research_summarizer.agent.judge_evidence") as mock_judge:
                run_agent(request)
            mock_judge.assert_not_called()

    def test_search_flow_reports_judging_progress(self):
        model = _mock_model(_summary_json("https://example.com/story", "body"))
        item = _item("R", "body")
        stages = []

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=_evidence_result(item)), \
             patch("research_summarizer.agent.judge_evidence",
                   return_value=_evidence_result(item)):
            run_agent("latest AI news", on_progress=lambda stage, _: stages.append(stage))

        assert stages[0] == "execute"
        assert "judge" in stages
        assert stages[-1] == "done"

    def test_run_agent_makes_exactly_one_llm_call(self):
        model = _mock_model(_summary_json("https://example.com/story", "body"))
        bound = model.bind.return_value
        item = _item("R", "body")

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=_evidence_result(item)), \
             patch("research_summarizer.agent.judge_evidence",
                   return_value=_evidence_result(item)):
            run_agent("latest AI news")

        assert bound.invoke.call_count == 1

    def test_progress_callback_invoked(self):
        model = _mock_model(_summary_json("https://example.com", "content"))
        stages = []

        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.evidence.fetch_url", return_value="content"):
            run_agent("https://example.com", on_progress=lambda stage, msg: stages.append(stage))

        assert stages[0] == "execute"
        assert "summarize" in stages
        assert stages[-1] == "done"

    def test_rejects_citation_not_in_selected_search_evidence(self):
        selected = _evidence_result(_item("Selected", "real content"))
        dropped = _item("Dropped", "other content", id_="S2", url="https://example.com/drop")
        model = _mock_model(_summary_json(dropped.url))
        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.agent.search_web_items",
                   return_value=_evidence_result(selected.items[0], dropped)), \
             patch("research_summarizer.agent.judge_evidence", return_value=selected), \
             pytest.raises(ParseError, match="Source validation failed"):
            run_agent("topic")

    def test_file_path_cannot_cite_web_source(self):
        model = _mock_model(_summary_json("https://example.com/invented"))
        with patch("research_summarizer.agent.build_model", return_value=model), \
             patch("research_summarizer.evidence.read_text_file", return_value="File content."), \
             pytest.raises(ParseError, match="Source validation failed"):
            run_agent("README.md")
