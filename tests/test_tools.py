import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from research_summarizer.agent import (
    _normalize_url,
    fetch_url,
    read_text_file,
    search_web,
)


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


class SearchWebTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("research_summarizer.agent.load_dotenv")
    def test_requires_serpapi_key(self, mock_load_dotenv):
        result = search_web.invoke({"query": "example story"})
        self.assertIn("missing SERPAPI_API_KEY", result)
        mock_load_dotenv.assert_called_once()

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent.serpapi.Client")
    def test_parses_results(self, mock_client_class):
        mock_client = mock_client_class.return_value
        mock_client.search.return_value = {
            "organic_results": [
                {
                    "title": "Example Story",
                    "link": "https://example.com/story",
                    "snippet": "Useful search snippet.",
                }
            ]
        }

        result = search_web.invoke({"query": "example story"})

        self.assertIn("Title: Example Story", result)
        self.assertIn("URL: https://example.com/story", result)
        self.assertIn("Snippet: Useful search snippet.", result)
        mock_client_class.assert_called_once_with(api_key="test-key", timeout=15)
        mock_client.search.assert_called_once_with(
            {"engine": "google", "q": "example story", "num": 5, "hl": "en"}
        )

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent._now")
    @patch("research_summarizer.agent.serpapi.Client")
    def test_corrects_stale_year_in_freshness_query(self, mock_client_class, mock_now):
        mock_now.return_value = datetime(2026, 5, 24, tzinfo=ZoneInfo("America/Los_Angeles"))
        mock_client_class.return_value.search.return_value = {"organic_results": []}

        search_web.invoke({"query": "Trump visit China 2025 latest news"})

        mock_client_class.return_value.search.assert_called_once_with(
            {"engine": "google", "q": "Trump visit China 2026 latest news", "num": 5, "hl": "en"}
        )

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent.serpapi.Client")
    def test_preserves_historical_year(self, mock_client_class):
        mock_client_class.return_value.search.return_value = {"organic_results": []}

        search_web.invoke({"query": "Trump China policy 2020 analysis"})

        mock_client_class.return_value.search.assert_called_once_with(
            {"engine": "google", "q": "Trump China policy 2020 analysis", "num": 5, "hl": "en"}
        )

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent.serpapi.Client")
    def test_reports_serpapi_error(self, mock_client_class):
        mock_client_class.return_value.search.return_value = {"error": "Invalid API key."}

        result = search_web.invoke({"query": "example story"})

        self.assertIn("Search failed: Invalid API key.", result)


class UrlNormalizationTests(unittest.TestCase):
    def test_strips_utm_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social&keep=1"
        result = _normalize_url(url)
        self.assertEqual(result, "https://example.com/article?keep=1")

    def test_strips_tracking_ref(self):
        url = "https://substack.com/post?r=abc123&valid=keep"
        result = _normalize_url(url)
        self.assertEqual(result, "https://substack.com/post?valid=keep")

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/page?id=42&sort=desc"
        result = _normalize_url(url)
        self.assertIn("id=42", result)
        self.assertIn("sort=desc", result)

    def test_clean_url_unchanged(self):
        url = "https://example.com/article"
        result = _normalize_url(url)
        self.assertEqual(result, url)


class ToolRegistryTests(unittest.TestCase):
    def test_contains_expected_tools(self):
        from research_summarizer.agent import _TOOL_REGISTRY

        tool_names = [t.name for t in _TOOL_REGISTRY]
        self.assertIn("search_web", tool_names)
        self.assertIn("fetch_url", tool_names)
        self.assertIn("read_text_file", tool_names)

    def test_get_tools_returns_copy(self):
        from research_summarizer.agent import _TOOL_REGISTRY, get_tools

        tools = get_tools()
        self.assertEqual(tools, _TOOL_REGISTRY)
        self.assertIsNot(tools, _TOOL_REGISTRY)

        tools.append("fake")
        self.assertNotIn("fake", _TOOL_REGISTRY)

    def test_build_agent_uses_registry_by_default(self):
        from research_summarizer.agent import build_agent

        agent = build_agent()
        self.assertIsNotNone(agent)

    def test_build_agent_accepts_custom_tools(self):
        from research_summarizer.agent import build_agent, search_web

        agent = build_agent(tools=[search_web])
        self.assertIsNotNone(agent)


class FetchUrlTests(unittest.TestCase):
    def setUp(self):
        from research_summarizer import agent

        agent._fetch_cache.clear()

    @patch("research_summarizer.agent.requests.get")
    def test_returns_page_text(self, mock_get):
        mock_response = Mock()
        mock_response.text = (
            "<html><head><title>Test Page</title></head>"
            "<body><p>Hello world.</p></body></html>"
        )
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = fetch_url.invoke({"url": "https://example.com"})

        self.assertIn("Title: Test Page", result)
        self.assertIn("URL: https://example.com", result)
        self.assertIn("Hello world.", result)

    @patch("research_summarizer.agent.requests.get")
    def test_caches_duplicate_url(self, mock_get):
        mock_response = Mock()
        mock_response.text = "<html><head><title>Page</title></head><body>Content</body></html>"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        first = fetch_url.invoke({"url": "https://example.com/article"})
        second = fetch_url.invoke({"url": "https://example.com/article"})

        self.assertEqual(mock_get.call_count, 1)
        self.assertIn("[CACHED", second)
        self.assertIn("Content", second)

    @patch("research_summarizer.agent.requests.get")
    def test_caches_tracking_param_variant(self, mock_get):
        mock_response = Mock()
        mock_response.text = "<html><head><title>Page</title></head><body>Content</body></html>"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        fetch_url.invoke({"url": "https://example.com/post?utm_source=twitter&r=abc"})
        second = fetch_url.invoke({"url": "https://example.com/post"})

        self.assertEqual(mock_get.call_count, 1)
        self.assertIn("[CACHED", second)

    @patch("research_summarizer.agent.requests.get")
    def test_http_error_returns_error_text(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = __import__("requests").HTTPError(
            "403 Forbidden", response=mock_response
        )
        mock_get.return_value = mock_response

        result = fetch_url.invoke({"url": "https://nytimes.com/article"})

        self.assertIn("[FETCH_ERROR] Source unavailable", result)
        self.assertIn("HTTP 403", result)

    @patch("research_summarizer.agent.requests.get")
    def test_network_error_returns_error_text(self, mock_get):
        mock_get.side_effect = __import__("requests").ConnectionError("Connection refused")

        result = fetch_url.invoke({"url": "https://down.example.com"})

        self.assertIn("[FETCH_ERROR] Network failure", result)
        self.assertIn("Connection refused", result)

    @patch("research_summarizer.agent.requests.get")
    def test_http_error_not_cached(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = __import__("requests").HTTPError(
            "403 Forbidden", response=mock_response
        )
        mock_get.return_value = mock_response

        fetch_url.invoke({"url": "https://paywall.example.com/article"})
        result = fetch_url.invoke({"url": "https://paywall.example.com/article"})

        self.assertEqual(mock_get.call_count, 2)
        self.assertNotIn("[CACHED", result)


if __name__ == "__main__":
    unittest.main()
