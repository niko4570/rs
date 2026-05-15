# Update Plan for DeepSeek V4 Pro Agent

## Context

The project will continue using `deepseek-v4-pro`.

Latest LangSmith testing showed that the model sometimes says its knowledge cutoff is `2025.4`, even when the real current date is `2026-05-14`. This is a model-behavior problem, not only a code bug. The agent must therefore be changed so it does not rely on the model's internal date or memory for current events.

## Problems to Fix

1. The model may use an outdated internal date.

   In the latest trace, the model treated `2026-05-13` as a future or uncertain date because it said its knowledge cutoff was `2025.4`.

2. The system prompt does not force the agent to trust the runtime date.

   The current prompt says to search for broad topics, but it does not explicitly tell the model that the current date comes from the application runtime and should override the model's internal knowledge cutoff.

3. Current-event questions need mandatory web research.

   For news, politics, recent events, market data, laws, or other time-sensitive topics, the agent should always search the web first before answering.

4. The final answer should mention source dates.

   When summarizing recent news, the agent should include article publication dates when available. This helps the user see whether the answer is based on current sources.

5. The agent can still run too long.

   Even when the answer succeeds, LangSmith showed long runtimes. The agent needs clearer limits on tool calls and runtime.

6. Fetched pages can be clipped without telling the model.

   The latest LangSmith trace showed this with the prompt:

   ```text
   summarize this post https://open.substack.com/pub/simonw/p/vibe-coding-and-agentic-engineering?utm_source=share&utm_medium=android&r=6dwq62
   ```

   The run succeeded, but the model repeatedly said the page was truncated and tried several near-duplicate fetches:

   - `https://open.substack.com/pub/simonw/p/vibe-coding-and-agentic-engineering`
   - `https://open.substack.com/pub/simonw/p/vibe-coding-and-agentic-engineering?utm_source=share&utm_medium=android&r=6dwq62`
   - `https://simonw.substack.com/p/vibe-coding-and-agentic-engineering`
   - `https://simonwillison.net/2026/May/6/vibe-coding-and-agentic-engineering/`
   - `https://news.ycombinator.com/item?id=48037128`

   This was not only a website problem. The current `fetch_url` implementation trims extracted page text with `_clean_text(..., 8000)`, and the tool output gives no explicit notice that the text was clipped. The model saw text ending mid-sentence, guessed that the page was truncated, and wasted extra tool calls.

## Implementation Changes Needed

1. Inject the real current date into the system prompt.

   Add a helper such as:

   ```python
   from datetime import datetime
   from zoneinfo import ZoneInfo

   def _runtime_context() -> str:
       now = datetime.now(ZoneInfo("America/Los_Angeles"))
       return f"Current date: {now:%Y-%m-%d}. Timezone: America/Los_Angeles."
   ```

   Then include this context when creating the agent.

2. Strengthen the system prompt.

   Add instructions like:

   ```text
   The current date is provided by the application runtime. Trust that date over your internal knowledge cutoff.
   For current or recent events, do not answer from memory. Search the web first, compare sources, and cite the sources used.
   If your internal knowledge cutoff conflicts with web sources or the runtime date, say that you are relying on current web sources.
   ```

3. Add current-event routing logic.

   Before invoking the agent, detect time-sensitive requests with keywords such as:

   - today
   - yesterday
   - latest
   - recent
   - news
   - 2026
   - 当前
   - 最新
   - 昨天
   - 今天
   - 新闻

   If detected, prepend a short instruction to the user request:

   ```text
   This is a current-event request. Use web search before answering. Use the runtime current date, not your internal cutoff.
   ```

4. Add a recursion limit to `agent.invoke`.

   Example:

   ```python
   result = agent.invoke(
       {"messages": [{"role": "user", "content": request}]},
       config={"recursion_limit": 10},
   )
   ```

   This prevents the agent from repeatedly searching and fetching for too long.

5. Reduce duplicate URL fetching.

   Add logic or prompt rules that tell the agent:

   ```text
   Fetch at most 3-5 high-quality sources. Do not fetch the same URL twice. Prefer article pages over index pages, search pages, or Wikipedia for current news.
   ```

6. Make page clipping explicit.

   Change `fetch_url` so it tells the model when content was clipped. For example, return metadata like:

   ```text
   Content clipped: yes
   Returned characters: 8000
   Original extracted characters: 24500
   ```

   Also add a clear marker at the end:

   ```text
   [CONTENT CLIPPED: use a follow-up fetch with a later chunk if more detail is required.]
   ```

   This prevents the model from treating clipped text as a mysterious website failure.

7. Add chunked page reading.

   Add optional arguments to `fetch_url`, such as:

   ```python
   def fetch_url(url: str, start: int = 0, max_chars: int = 8000) -> str:
   ```

   The tool should return the requested slice of cleaned page text and include whether more content exists. Then the agent can fetch the next chunk instead of refetching the same URL.

8. Normalize URLs before duplicate checks.

   Strip tracking query parameters such as `utm_source`, `utm_medium`, and `r` before deciding whether a URL was already fetched. In the latest trace, the agent fetched multiple versions of the same Substack article because the URLs looked different even though they represented the same page.

9. Add source fallback rules for article URLs.

   If a Substack/open-substack URL looks clipped, the agent should try one canonical source URL once, then stop. For Simon Willison posts, the canonical `simonwillison.net` page was available and higher quality than repeated Substack refetches.

10. Improve CLI progress output.

   The CLI should print a short message before running:

   ```text
   Running research agent... check LangSmith for detailed trace.
   ```

   A later improvement can stream intermediate tool events, but a simple status message is enough for the next step.

11. Add tests.

   Add tests for:

   - runtime date context exists in the agent prompt
   - current-event requests are marked as requiring web search
   - `agent.invoke` uses a recursion limit
   - DeepSeek thinking mode remains disabled for `deepseek-v4-*`
   - `fetch_url` reports when content is clipped
   - `fetch_url` can return a later content chunk
   - duplicate URL detection treats tracking-parameter variants as the same page

## Expected Result

After these changes, the agent can still use `deepseek-v4-pro`, but it should:

1. Trust the real runtime date instead of the model's internal cutoff.
2. Search the web before answering current-event questions.
3. Cite current sources instead of relying on memory.
4. Avoid very long loops.
5. Be easier to observe from the CLI and LangSmith.
6. Know when a fetched page is clipped and fetch the next chunk only when needed.
7. Avoid repeated fetches of the same article under slightly different URLs.
