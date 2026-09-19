"""Unit tests for research summarizer tools — pytest edition."""

from unittest.mock import Mock

from tavily import InvalidAPIKeyError

from research_summarizer.evidence import (
    _normalize_url,
    fetch_url,
    read_text_file,
    search_web,
)

# ---------------------------------------------------------------------------
# read_text_file
# ---------------------------------------------------------------------------


def test_reads_project_file(temp_project_root):
    source = temp_project_root / "source.md"
    source.write_text("Research notes about LangChain.", encoding="utf-8")
    result = read_text_file(str(source))
    assert "Research notes about LangChain." in result


def test_refuses_outside_project(temp_project_root):
    result = read_text_file("/etc/passwd")
    assert "Refusing to read outside" in result


def test_resolves_relative_paths(temp_project_root):
    source = temp_project_root / "notes.md"
    source.write_text("Relative path content.", encoding="utf-8")
    result = read_text_file("notes.md")
    assert "Relative path content." in result


# ---------------------------------------------------------------------------
# search_web
# ---------------------------------------------------------------------------


def test_search_web_requires_api_key(no_tavily_key, mocker):
    mock_load_dotenv = mocker.patch("research_summarizer.evidence.load_dotenv")
    result = search_web("example story")
    assert "missing TAVILY_API_KEY" in result
    mock_load_dotenv.assert_called_once()


def test_parses_results(mock_tavily_key, mocker):
    mock_client_class = mocker.patch("research_summarizer.evidence.TavilyClient")
    mock_client = mock_client_class.return_value
    mock_client.search.return_value = {
        "results": [
            {
                "title": "Example Story",
                "url": "https://example.com/story",
                "content": "Useful search snippet.",
            }
        ]
    }

    result = search_web("example story")

    assert "Title: Example Story" in result
    assert "URL: https://example.com/story" in result
    assert "Snippet: Useful search snippet." in result
    mock_client_class.assert_called_once_with(api_key="test-key")
    mock_client.search.assert_called_once_with(query="example story", max_results=5, timeout=15)


def test_passes_freshness_query_through_unchanged(mock_tavily_key, mocker):
    mock_client_class = mocker.patch("research_summarizer.evidence.TavilyClient")
    mock_client_class.return_value.search.return_value = {"results": []}

    search_web("Trump visit China 2025 latest news")

    mock_client_class.return_value.search.assert_called_once_with(
        query="Trump visit China 2025 latest news", max_results=5, timeout=15
    )


def test_reports_tavily_error(mock_tavily_key, mocker):
    mock_client_class = mocker.patch("research_summarizer.evidence.TavilyClient")
    mock_client_class.return_value.search.side_effect = InvalidAPIKeyError("Invalid API key.")

    result = search_web("example story")

    assert "Search failed: Invalid API key." in result


# ---------------------------------------------------------------------------
# _normalize_url
# ---------------------------------------------------------------------------


def test_strips_utm_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&keep=1"
    result = _normalize_url(url)
    assert result == "https://example.com/article?keep=1"


def test_strips_tracking_ref():
    url = "https://substack.com/post?r=abc123&valid=keep"
    result = _normalize_url(url)
    assert result == "https://substack.com/post?valid=keep"


def test_preserves_non_tracking_params():
    url = "https://example.com/page?id=42&sort=desc"
    result = _normalize_url(url)
    assert "id=42" in result
    assert "sort=desc" in result


def test_clean_url_unchanged():
    url = "https://example.com/article"
    result = _normalize_url(url)
    assert result == url


# ---------------------------------------------------------------------------
# fetch_url
# ---------------------------------------------------------------------------


def test_fetch_returns_page_text(mocker):
    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_response = Mock()
    mock_response.text = (
        "<html><head><title>Test Page</title></head>"
        "<body><p>Hello world.</p></body></html>"
    )
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    result = fetch_url("https://example.com")

    assert "Title: Test Page" in result
    assert "URL: https://example.com" in result
    assert "Hello world." in result


def test_fetch_caches_duplicate_url(mocker):
    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_response = Mock()
    mock_response.text = "<html><head><title>Page</title></head><body>Content</body></html>"
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    fetch_url("https://example.com/article")
    second = fetch_url("https://example.com/article")

    assert mock_get.call_count == 1
    assert "[CACHED" in second
    assert "Content" in second


def test_fetch_caches_tracking_param_variant(mocker):
    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_response = Mock()
    mock_response.text = "<html><head><title>Page</title></head><body>Content</body></html>"
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    fetch_url("https://example.com/post?utm_source=twitter&r=abc")
    second = fetch_url("https://example.com/post")

    assert mock_get.call_count == 1
    assert "[CACHED" in second


def test_fetch_http_error_returns_error_text(mocker):
    import requests as req

    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.raise_for_status.side_effect = req.HTTPError(
        "403 Forbidden", response=mock_response
    )
    mock_get.return_value = mock_response

    result = fetch_url("https://nytimes.com/article")

    assert "[FETCH_ERROR] Source unavailable" in result
    assert "HTTP 403" in result


def test_fetch_network_error_returns_error_text(mocker):
    import requests as req

    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_get.side_effect = req.ConnectionError("Connection refused")

    result = fetch_url("https://down.example.com")

    assert "[FETCH_ERROR] Network failure" in result
    assert "Connection refused" in result


def test_fetch_http_error_not_cached(mocker):
    import requests as req

    mock_get = mocker.patch("research_summarizer.evidence.requests.get")
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.raise_for_status.side_effect = req.HTTPError(
        "403 Forbidden", response=mock_response
    )
    mock_get.return_value = mock_response

    fetch_url("https://paywall.example.com/article")
    result = fetch_url("https://paywall.example.com/article")

    assert mock_get.call_count == 2
    assert "[CACHED" not in result
