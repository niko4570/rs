# Update Plan — Search Date Correction and Stateful Fetch Cache

## Context

LangSmith traces from 2026-05-18 and 2026-05-24 revealed two related failure modes:

1. The agent runs open-loop, with no memory of what it already fetched within a single `run_agent()` call. As context grows past 8-10 turns with full page texts, earlier tool results fall out of the model's attention window. The model then repeats work and chases dead ends.
2. For fresh-news prompts, the model can insert a stale year such as `2025` even after the current year is known. Forcing every query through `after:<today>` was too restrictive, so the date fix now happens inside `search_web`: stale years are corrected only for freshness-oriented queries.

Adding a URL fetch cache that lasts for one run fixes repeated fetches and dead-source handling. Moving stale-year correction into `search_web` fixes date drift without requiring the model to remember a separate tool call.

## Design: Stale-year correction inside `search_web`

Freshness-oriented queries are detected by words such as `latest`, `recent`, `today`, `current`, `news`, and `updates`. When such a query contains a stale recent year, `search_web` rewrites it to the real current year before sending it to SerpApi.

```python
freshness_query = re.search(
    r"\b(latest|recent|today|current|now|news|updates?|this\s+(?:week|month|year))\b",
    query,
    flags=re.IGNORECASE,
)
if freshness_query:
    current_year = _now().year
    stale_years = {str(year) for year in range(current_year - 3, current_year)}
    query = re.sub(
        r"\b20\d{2}\b",
        lambda match: str(current_year) if match.group(0) in stale_years else match.group(0),
        query,
    )
```

Examples:

| Input query | Sent to SerpApi |
|-------------|-----------------|
| `Trump visit China 2025 latest news` | `Trump visit China 2026 latest news` |
| `Trump China policy 2020 analysis` | `Trump China policy 2020 analysis` |

This avoids the broken `after:<today>` behavior, which excluded useful existing pages from ordinary research searches.

## Design: In-memory fetch cache per run

A module-level `dict` mapping normalized URL → (status, content):

```
_fetch_cache: dict[str, str] = {}
```

Cleared at the start of each `run_agent()` call. Lives only for that one invocation — different queries get fresh caches.

### URL normalization

Strip tracking query params before checking the cache:

```python
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "r", "fbclid", "gclid", "ref", "source"}

def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(params)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
```

So `https://substack.com/post?utm_source=share&r=abc` and `https://substack.com/post` both map to the same cache key.

### Tool behavior

```python
@tool
def fetch_url(url: str) -> str:
    normalized = _normalize_url(url)
    
    if normalized in _fetch_cache:
        return f"[CACHED] {_fetch_cache[normalized]}"
    
    # ... fetch and parse ...
    
    if http_error:
        # Don't cache failures — model can't "trust" dead sources later
        raise RuntimeError(f"URL fetch failed: HTTP {status_code}")
    
    result = f"Title: {title}\nURL: {url}\nText: {body}"
    _fetch_cache[normalized] = result
    return result
```

### What this fixes

| Symptom | How cache resolves it |
|---------|----------------------|
| Duplicate fetches (same URL with diff params) | Normalization → cache hit, no API call |
| Index page fetches after articles from same domain | Cache shows domain already covered; model sees `[CACHED]` and knows |
| Dead sources trusted (Reuters 401) | Not cached → can't be returned later; RuntimeError → LangSmith marks error |
| Stale year in fresh-news search | `search_web` corrects stale recent years before calling SerpApi |
| 13 tool calls for one query | Cache eliminates ~4-5 redundant fetch calls |

### CLI progress message

One line in `cli.py`:

```python
print("Running research agent... (check LangSmith for detailed trace)", flush=True)
```

## Implementation Steps

1. Add `_now()` and stale-year correction inside `search_web`
2. Keep normal historical searches unchanged; do not append `after:<today>`
3. Add `_normalize_url()` and `_fetch_cache` to `agent.py`
4. Rewrite `fetch_url` to use cache + raise on HTTP errors
5. Add `_fetch_cache.clear()` at top of `run_agent()`
6. Add one-line CLI progress message in `cli.py`
7. Run tests, then re-test on a fresh-news query to measure improvement
