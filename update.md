# Update Plan — Stateful Fetch Cache

## Context

LangSmith traces from 2026-05-18 revealed four symptoms that share one root cause: the agent runs open-loop, with no memory of what it already fetched within a single `run_agent()` call. As context grows past 8-10 turns with full page texts, earlier tool results fall out of the model's attention window. The model then repeats work, chases dead ends, and forgets dates.

Adding a URL fetch cache that lasts for one run fixes the root cause instead of patching each symptom.

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
| `current_time` forgotten | Fewer total fetches → shorter context → model retains early results |
| 13 tool calls for one query | Cache eliminates ~4-5 redundant fetch calls |

### CLI progress message

One line in `cli.py`:

```python
print("Running research agent... (check LangSmith for detailed trace)", flush=True)
```

## Implementation Steps

1. Add `_normalize_url()` and `_fetch_cache` to `agent.py`
2. Rewrite `fetch_url` to use cache + raise on HTTP errors
3. Add `_fetch_cache.clear()` at top of `run_agent()`
4. Add one-line CLI progress message in `cli.py`
5. Run tests, then re-test on Russia-Ukraine query to measure improvement

