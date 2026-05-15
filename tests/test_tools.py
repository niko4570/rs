import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_summarizer.agent import read_text_file, search_web


class ReadTextFileTests(unittest.TestCase):
    def test_read_text_file_reads_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("Research notes about LangChain.", encoding="utf-8")

            with patch("pathlib.Path.cwd", return_value=root.resolve()):
                result = read_text_file.invoke({"path": str(source)})

            self.assertIn("Research notes about LangChain.", result)

    def test_read_text_file_refuses_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with patch("pathlib.Path.cwd", return_value=root.resolve()):
                result = read_text_file.invoke({"path": "/etc/passwd"})

            self.assertIn("Refusing to read outside", result)


class SearchWebTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("research_summarizer.agent.load_dotenv")
    def test_search_web_requires_serpapi_key(self, mock_load_dotenv):
        result = search_web.invoke({"query": "example story"})

        self.assertIn("missing SERPAPI_API_KEY", result)
        mock_load_dotenv.assert_called_once()

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent.serpapi.Client")
    def test_search_web_parses_serpapi_results(self, mock_client_class):
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
            {
                "engine": "google",
                "q": "example story",
                "num": 5,
                "hl": "en",
            }
        )

    @patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"})
    @patch("research_summarizer.agent.serpapi.Client")
    def test_search_web_reports_serpapi_error(self, mock_client_class):
        mock_client_class.return_value.search.return_value = {"error": "Invalid API key."}

        result = search_web.invoke({"query": "example story"})

        self.assertIn("Search failed: Invalid API key.", result)


if __name__ == "__main__":
    unittest.main()
