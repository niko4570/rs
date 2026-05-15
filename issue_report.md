# Agent Issue Report

## Context

This report summarizes the latest LangSmith test results for the `research_summarizer` agent and lists the current issues observed during local testing.

Project: `research-summarizer-agent`

## LangSmith Test Results

Recent top-level runs observed in LangSmith:

| Prompt                                                                                                         | Status  | Latency | Notes                                         |
| -------------------------------------------------------------------------------------------------------------- | ------- | ------: | --------------------------------------------- |
| `Summarize README.md in 2 bullets`                                                                             | Success |  ~17.6s | Local file reading and summarization worked.  |
| `Summarize README.md in 2 bullets`                                                                             | Error   |  ~14.3s | Failed before the DeepSeek thinking-mode fix. |
| `搜索关于特朗普访华的最新新闻。Compare multiple sources and give me a beginner-friendly summary with sources.` | Success | ~386.8s | Completed, but took over 6 minutes.           |
| `Research news about Trump visiting China in May 2026. Give a beginner-friendly summary with sources.`         | Success | ~297.7s | Completed, but took about 5 minutes.          |

## Current Agent Problems

1. Web research runs are too slow.

   The agent can finish web research tasks, but recent LangSmith traces show latencies around 5-6 minutes. From the terminal, this looks like the agent is stuck or hanging.

2. The CLI gives no progress feedback.

   While the agent is working, the user sees no intermediate status. Long-running web research tasks therefore appear frozen even when LangSmith shows the run is still active.

3. [x] The search tool is fragile.

   Fixed by replacing HTML scraping with SerpApi's Google search SDK integration.

4. The agent may fetch broad news index pages instead of specific articles.

   LangSmith showed `fetch_url` calls to pages such as BBC China news index pages and AP topic pages. These are less precise than article URLs and can add noise or latency.

5. Failed URL fetches are treated as successful tool runs.

   Example from LangSmith: a CNN URL returned a `404 Client Error`, but the tool run itself had status `success` because the tool returned the error as text. This makes debugging harder and may encourage the model to continue using weak sources.

6. There is no explicit max runtime or iteration guard.

   The agent currently relies on the default LangChain/LangGraph behavior. For web research, the project should add clearer limits so the agent fails fast or returns partial results instead of running for several minutes.

7. DeepSeek `deepseek-v4-pro` required a provider-specific workaround.

   Earlier LangSmith traces showed a `400` error: `The reasoning_content in the thinking mode must be passed back to the API.` This was caused by DeepSeek thinking mode with tool calls. The project now disables thinking mode for `deepseek-v4-*` models, but this provider-specific behavior should be documented and tested.

## Recommended Fixes

1. Add a max runtime or timeout for full agent runs.
2. Add a max iteration/tool-call limit for web research.
3. Improve CLI progress output so users can see when search, fetch, and model steps are happening.
4. [x] Replace HTML search scraping with a more reliable search provider API.
5. Prefer specific article URLs over broad news/category pages.
6. Mark failed fetches more clearly so the agent can avoid treating them as useful sources.
7. Add tests for DeepSeek model configuration and web-tool failure cases.
