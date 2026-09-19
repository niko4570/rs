# AGENTS.md

## Project

`rs` is a small, local-first research summarizer. It accepts one user request, acquires evidence through a deterministic route, performs one LLM synthesis call, and returns a validated `SummaryResult`.

Current stack:

- Python 3.11+
- FastAPI + Uvicorn
- Pydantic
- `langchain-openai` as the LLM client integration
- Tavily for topic/web search
- `requests` + `trafilatura` for direct URL fetching
- Python standard library for local text files
- `pytest` + `pytest-mock` for tests
- Ruff, line length 100
- Optional LangSmith tracing

The project is local-first, not a SaaS platform and not a general-purpose autonomous agent framework.

## Product Boundary

Supported inputs:

1. A topic or research question
2. An `http://` or `https://` URL
3. A local `.txt`, `.md`, or `.markdown` file within the project root

The system should return a structured summary based only on acquired evidence. If evidence is missing, weak, contradictory, or unavailable, the result must communicate that limitation through the model's caveats rather than inventing information.

Out of scope unless explicitly requested:

- Multi-user accounts or authentication
- Database, vector database, or persistent memory
- RAG infrastructure
- MCP servers
- Multi-agent systems
- Planner, replanner, critic, reflection, or repair stages
- Autonomous tool loops
- Background workers, queues, Redis, Celery, or RabbitMQ
- WebSockets, SSE, or streaming infrastructure
- Cloud deployment infrastructure
- General-purpose time-awareness services

## Architecture

The canonical workflow is:

```text
User Request
    ↓
Deterministic Dispatch
    ├── URL → fetch_url()
    ├── Local text path → read_text_file()
    └── Topic/question → search_web() via Tavily
                            ↓
                         Evidence
                            ↓
                   One LLM synthesis call
                            ↓
                    Deterministic parsing
                            ↓
                       SummaryResult
```

Core principle:

> Tools acquire evidence; the LLM synthesizes evidence; Python validates the output.

The workflow must remain readable from top to bottom. Prefer explicit functions and simple data flow over abstractions that hide execution order.

## Module Responsibilities

### `research_summarizer/agent.py`

Owns the top-level workflow:

- Clear the per-run fetch cache
- Build the configured model
- Resolve the request deterministically
- Acquire evidence through the selected tool
- Call the summarizer exactly once
- Parse and validate the model output
- Emit optional progress callbacks

Do not move network, filesystem, or LLM orchestration into the API or CLI layers.

### `research_summarizer/evidence.py`

This is the only module that performs network or filesystem evidence acquisition.

It owns:

- Tavily search
- Direct URL fetching and extraction
- Per-run URL cache and URL normalization
- Local text-file reading and project-root boundary checks
- Evidence formatting and bounded text handling

For Tavily:

- Use `TavilyClient` with `TAVILY_API_KEY`.
- Keep the call deterministic and bounded, normally with at most five results.
- Do not request Tavily's answer synthesis; the project LLM is responsible for synthesis.
- Prefer `raw_content` when present; fall back to Tavily's `content` field when necessary.
- Preserve source title and URL.
- Apply explicit per-source and total evidence limits so a search cannot overflow the LLM context.
- Do not pass the entire raw Tavily response or unrelated metadata to the LLM.
- Do not fabricate missing title, URL, or content.
- Handle empty results and Tavily/network errors explicitly.

For direct URLs:

- Accept only HTTP(S) URLs.
- Preserve the existing request timeout, extraction behavior, URL normalization, and per-run cache unless a requirement justifies changing them.
- Return a clear fetch error when the page is unavailable or has no extractable content.

For local files:

- Allow only supported text extensions.
- Read as UTF-8.
- Preserve the existing project-root path boundary protection.
- Do not allow path traversal or reading arbitrary files outside the project root.

### `research_summarizer/summarizer.py`

Owns LLM configuration and the single synthesis call.

Required environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Responsibilities:

- Build the OpenAI-compatible `ChatOpenAI` client
- Send the request and prepared evidence to the model
- Return raw model output

The summarizer must not perform searches, URL fetching, file access, planning, parsing, or validation repair. Normal research execution must make exactly one LLM call. Retries are acceptable only for explicitly handled transient transport/API failures and must not become additional reasoning stages.

### `research_summarizer/parser.py`

Owns deterministic extraction, JSON parsing, and Pydantic validation. Invalid output should raise or return a clear parsing/validation error. Do not add another LLM call to repair malformed output.

### `research_summarizer/models.py`

Contains the Pydantic data models, including `SummaryResult`. Keep schemas separate from workflow logic.

### `research_summarizer/prompts.py`

Prompts must instruct the model to:

- Use only supplied evidence
- Avoid unsupported claims
- Distinguish evidence from inference
- Report uncertainty and conflicting sources
- Include only sources present in the evidence
- Return the required JSON structure

Prompts must not implement control flow that belongs in deterministic Python.

### `research_summarizer/api.py`

Thin FastAPI adapter. It owns endpoint concerns only:

- `/api/health`
- `/api/research`
- Request validation
- Local text-file upload handling
- Calling the shared research workflow
- Mapping expected failures to HTTP responses
- Local development CORS

Do not duplicate research logic here.

### `research_summarizer/cli.py`

Local command-line adapter. It must call the same core workflow used by the API and must not duplicate evidence acquisition or summarization logic.

## LLM and Evidence Contract

The normal contract is:

```text
Prepared evidence → one LLM call → JSON text → parser → SummaryResult
```

Evidence formatting may evolve, but it must remain clear, bounded, and source-attributed. If the evidence format changes, update the related tests and prompt expectations together.

The LLM is not a source of new facts. It may synthesize, compare, and qualify information present in the evidence, but it must not claim that it performed additional searches or consulted sources that were not supplied.

## Security and Reliability

Preserve and test the existing protections for:

- HTTP(S)-only URL handling
- Invalid URL input
- Unsupported file extensions
- UTF-8 decoding failures
- Upload size limits
- Project-root path boundaries
- Path traversal attempts
- Network and external API failures
- Invalid model output

Never hide acquisition failures by fabricating evidence or summaries. Prefer explicit error text and a truthful caveat.

Do not log or expose API keys, uploaded file contents, or unnecessary personal data.

## Testing Requirements

Tests should primarily verify observable behavior and should not require live external APIs.

Mock Tavily, HTTP requests, and the LLM in unit tests. Integration tests may use real services only when explicitly identified and separately configured.

When changing Tavily integration, test at minimum:

- Missing `TAVILY_API_KEY`
- Successful search with the intended request parameters
- `raw_content` preferred over `content`
- Fallback when `raw_content` is absent or empty
- Evidence includes title and URL
- Per-source/total length limits
- Empty or malformed results
- Tavily API and timeout errors
- Evidence passed onward to the summarizer

Also maintain coverage for:

- Deterministic input dispatch
- URL validation and extraction
- URL cache behavior
- Local file boundaries and supported extensions
- Parser and Pydantic validation
- API and CLI contracts
- Expected error mapping

Tests should assert evidence content and behavior, not only that a mocked method was called.

## Change Discipline

Before editing:

1. Read the relevant implementation, tests, and this file.
2. Identify the existing contract that must remain stable.
3. Make the smallest change that satisfies the requirement.

After editing:

1. Update or add tests for changed behavior.
2. Run the relevant test subset, then the full test suite when practical.
3. Run Ruff on changed files.
4. Check that no obsolete architecture remains in documentation.
5. Confirm that no unnecessary dependency or infrastructure was introduced.
6. Review error paths and evidence quality, not only the happy path.

Do not perform speculative refactors. Do not reintroduce agent frameworks or additional LLM stages without a concrete, documented product requirement.

## Definition of Done

A change is complete only when:

- It matches the deterministic architecture above.
- Existing public API and CLI behavior remains compatible unless intentionally changed.
- Tests cover the new or modified behavior.
- External services are mocked in unit tests.
- Evidence is useful, bounded, and source-attributed.
- Failures are explicit and truthful.
- The normal path still uses one LLM synthesis call.
- Ruff and tests pass, or any failure is documented with its cause.
- This file is updated when architecture, contracts, or scope materially changes.
