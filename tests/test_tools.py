"""Unit tests for research summarizer tools — pytest edition."""

from unittest.mock import Mock

import requests
from tavily import InvalidAPIKeyError
from tavily.errors import TimeoutError as TavilyTimeoutError

from research_summarizer.evidence import (
    MAX_SEARCH_CONTENT_CHARS,
    MAX_SEARCH_EVIDENCE_CHARS,
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


def _mock_search(mocker, return_value):
    """Patch TavilyClient and return the mocked client's search method."""
    mock_client_class = mocker.patch("research_summarizer.evidence.TavilyClient")
    mock_search = mock_client_class.return_value.search
    mock_search.return_value = return_value
    return mock_client_class, mock_search


def test_search_web_requires_api_key(no_tavily_key, mocker):
    mock_load_dotenv = mocker.patch("research_summarizer.evidence.load_dotenv")
    result = search_web("example story")
    assert "missing TAVILY_API_KEY" in result
    mock_load_dotenv.assert_called_once()


def test_search_web_uses_supported_parameters(mock_tavily_key, mocker):
    mock_client_class, mock_search = _mock_search(mocker, {"results": []})

    search_web("example story")

    mock_client_class.assert_called_once_with(api_key="test-key")
    mock_search.assert_called_once_with(
        query="example story",
        search_depth="basic",
        topic="general",
        max_results=5,
        include_answer=False,
        include_raw_content="markdown",
        timeout=15,
    )


def test_search_web_passes_query_through_unchanged(mock_tavily_key, mocker):
    _, mock_search = _mock_search(mocker, {"results": []})

    search_web("Trump visit China 2025 latest news")

    assert mock_search.call_args.kwargs["query"] == "Trump visit China 2025 latest news"


def test_search_web_includes_title_and_url(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Example Story",
                    "url": "https://example.com/story",
                    "content": "Useful search snippet.",
                }
            ]
        },
    )

    result = search_web("example story")

    assert "Title: Example Story" in result
    assert "URL: https://example.com/story" in result


def test_search_web_prefers_raw_content(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Example Story",
                    "url": "https://example.com/story",
                    "raw_content": "# Full article\n\nSubstantive raw markdown body.",
                    "content": "Short fallback snippet.",
                }
            ]
        },
    )

    result = search_web("example story")

    assert "Content: # Full article" in result
    assert "Substantive raw markdown body." in result
    assert "Short fallback snippet." not in result


def test_search_web_falls_back_to_content_when_raw_content_missing(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Example Story",
                    "url": "https://example.com/story",
                    "content": "Fallback snippet body.",
                }
            ]
        },
    )

    result = search_web("example story")

    assert "Content: Fallback snippet body." in result


def test_search_web_falls_back_to_content_when_raw_content_empty(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Example Story",
                    "url": "https://example.com/story",
                    "raw_content": "   \n  ",
                    "content": "Fallback snippet body.",
                }
            ]
        },
    )

    result = search_web("example story")

    assert "Content: Fallback snippet body." in result


def test_search_web_preserves_markdown_structure(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Example Story",
                    "url": "https://example.com/story",
                    "raw_content": "# Heading\n\nParagraph one.\n\n- item a\n- item b",
                }
            ]
        },
    )

    result = search_web("example story")

    assert "# Heading\n\nParagraph one.\n\n- item a\n- item b" in result


def test_search_web_limits_per_source_content(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Long Source",
                    "url": "https://example.com/long",
                    "raw_content": "A" * (MAX_SEARCH_CONTENT_CHARS * 3),
                }
            ]
        },
    )

    result = search_web("example story")

    body = result.split("Content: ", 1)[1]
    assert len(body) == MAX_SEARCH_CONTENT_CHARS


def test_search_web_limits_total_evidence(mock_tavily_key, mocker):
    results = [
        {
            "title": f"Source {index}",
            "url": f"https://example.com/{index}",
            "raw_content": "B" * (MAX_SEARCH_CONTENT_CHARS * 3),
        }
        for index in range(5)
    ]
    _mock_search(mocker, {"results": results})

    result = search_web("example story")

    assert len(result) <= MAX_SEARCH_EVIDENCE_CHARS
    assert "Source 0" in result


def test_search_web_empty_results(mock_tavily_key, mocker):
    _mock_search(mocker, {"results": []})

    assert search_web("example story") == "No search results found."


def test_search_web_missing_results_key(mock_tavily_key, mocker):
    _mock_search(mocker, {})

    assert search_web("example story") == "No search results found."


def test_search_web_malformed_results(mock_tavily_key, mocker):
    _mock_search(mocker, {"results": "not-a-list"})

    assert search_web("example story") == "No search results found."


def test_search_web_skips_result_with_non_string_content(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {
                    "title": "Bad content",
                    "url": "https://example.com/bad",
                    "content": ["unexpected", "list"],
                }
            ]
        },
    )

    assert search_web("example story") == "No search results found."


def test_search_web_skips_missing_title_or_url(mock_tavily_key, mocker):
    _mock_search(
        mocker,
        {
            "results": [
                {"title": "", "url": "https://example.com/no-title", "content": "Body."},
                {"title": "No URL", "url": "", "content": "Body."},
                {
                    "title": "Valid",
                    "url": "https://example.com/valid",
                    "content": "Valid body.",
                },
                None,
            ]
        },
    )

    result = search_web("example story")

    assert result.count("Title:") == 1
    assert "Title: Valid" in result
    assert "URL: https://example.com/valid" in result
    assert "None" not in result


def test_search_web_reports_tavily_error(mock_tavily_key, mocker):
    _, mock_search = _mock_search(mocker, {})
    mock_search.side_effect = InvalidAPIKeyError("Invalid API key.")

    result = search_web("example story")

    assert "Search failed: Invalid API key." in result


def test_search_web_reports_timeout(mock_tavily_key, mocker):
    _, mock_search = _mock_search(mocker, {})
    mock_search.side_effect = TavilyTimeoutError(15)

    result = search_web("example story")

    assert "Search failed:" in result
    assert "timed out after 15 seconds" in result


def test_search_web_reports_network_error(mock_tavily_key, mocker):
    _, mock_search = _mock_search(mocker, {})
    mock_search.side_effect = requests.exceptions.ConnectionError("Connection refused")

    result = search_web("example story")

    assert "Search failed: Connection refused" in result


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
