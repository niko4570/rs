# Agent Issue Report

## Context

This report tracks issues observed during local testing of the `research_summarizer` agent, confirmed by LangSmith traces.

Project: `research-summarizer-agent`

## LangSmith Test Results

Recent top-level runs observed in LangSmith:

| Prompt | Status | Latency | Notes |
| ------ | ------ | ------: | ----- |
| `Check today's latest news about the Russia-Ukraine conflict` | Success | ~88s | 13 tool calls: `current_time` ✅, but 2 index-page fetches, 1 dead source (Reuters 401), 1 stale search ("2025") |
| `https://phys.org/news/2026-05-why-is-almost-everyone-right.html` | Success | ~32s | Clean: 1 `fetch_url`, done. |
| `summarize this post https://open.substack.com/...` | Success | ~83s | Multiple near-duplicate fetches of the same article under different URLs. |
| `研究并总结2026.5.13特朗普访华这一事件的影响` | Success | ~142s | Completed but excessive tool calls. |
| `研究并总结昨天特朗普访华这一事件的影响` | Error | ~158s | `APITimeoutError` — model request timed out during web research. |

## Current Agent Problems

1. [x] DeepSeek thinking mode `400` error.
   Fixed: disabled thinking for `deepseek-v4-*` models.

2. [x] Search tool was fragile (HTML scraping).
   Fixed: replaced with SerpApi SDK integration.

3. [x] Model didn't know current date.
   Fixed: added `current_time` tool so the agent checks the clock when needed.

4. The agent runs open-loop — no memory of what it already fetched.

   Every problem below shares one root cause: the agent doesn't track its own state within a run. Earlier tool results fall out of the model's attention window as context grows, causing it to repeat work, chase dead ends, and forget what it learned.

   Symptoms:
   - Failed fetches (Reuters 401) treated as usable sources
   - Index pages fetched after already having article content from the same domain
   - `current_time` result forgotten (searched "2025" after getting "2026-05-18")
   - 9 fetch calls + 3 searches for one news summary (13 total tool calls)

5. CLI gives no progress feedback.
   While the agent is working, the user sees no intermediate status.

## Root Cause

The LangChain agent loop is stateless between turns. Every turn, the model gets the full message history, but as context grows past 8-10 turns with full page texts injected, earlier tool results fall outside the model's attention window. The model then repeats fetches, chases index pages, forgets dates, and over-fetches — all different symptoms of the same underlying problem.

## Fix: Stateful fetch cache within a run

A URL fetch cache that lives for one `run_agent()` call addresses the root cause:
- Normalize URLs (strip tracking params) → cache hit on near-duplicates
- Return `[CACHED]` on hit → model sees it already has the content
- Don't cache failed fetches → dead sources can't be "trusted" later
- Raise on HTTP errors → LangSmith marks tool as error
- Shorter context (fewer duplicate fetches) → model keeps earlier results in attention

This one mechanism replaces four separate prompt-rule patches.

