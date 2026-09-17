# AGENTS.md

## Project Overview

`rs` is a small, local-only research summarizer.

The project accepts one of three input types:

- A research topic / question
- A URL
- A local `.txt` / `.md` / `.markdown` file

It acquires evidence, sends that evidence to an LLM for synthesis, and returns a structured `SummaryResult`.

The project is intentionally small. Do not introduce agentic orchestration unless there is a concrete requirement that cannot be solved more simply.

## Current Architecture

The core workflow is:

```text
User Request
    ↓
Deterministic Dispatch
    ├── URL → Fetch Web Page
    ├── Local File → Read File
    └── Topic → Tavily Search
                    ↓
                 Evidence
                    ↓
              One LLM Call
                    ↓
              Parse JSON
                    ↓
             SummaryResult
```

The important architectural principle is:

> Tools acquire evidence. The LLM synthesizes evidence.

The application is not intended to autonomously plan, re-plan, execute multi-step tasks, or maintain an agent loop.

## Core Components

### `research_summarizer/agent.py`

Contains the main research workflow and deterministic input dispatch.

Responsibilities include:

- Resolving the input type
- Calling the appropriate evidence-acquisition function
- Fetching URLs
- Reading local text files
- Searching topics with Tavily
- Constructing evidence for the LLM
- Calling the LLM exactly once
- Passing the result to the parser

Keep the workflow explicit and easy to follow.

Do not turn this module into a general-purpose autonomous agent framework.

### `research_summarizer/summarizer.py`

Contains the LLM summarization layer.

Responsibilities:

- Receiving prepared evidence
- Calling the configured LLM
- Returning the raw model output

The summarizer should not perform web searches, file access, planning, or validation loops.

### `research_summarizer/parser.py`

Contains deterministic parsing and validation of the LLM response.

Responsibilities:

- Extracting the JSON object from model output
- Validating the result with Pydantic
- Raising a parsing/validation error when the response is invalid

Do not add another LLM call for repairing malformed output.

### `research_summarizer/models.py`

Contains Pydantic models used by the application.

The primary output model is `SummaryResult`.

Keep data models separate from workflow logic.

### `research_summarizer/prompts.py`

Contains prompts used by the summarization layer.

The prompt should make the LLM:

- Use only supplied evidence
- Avoid unsupported claims
- Distinguish strong evidence from weak evidence
- Report uncertainty or conflicting information
- Return the required JSON structure
- Include only sources actually present in the evidence

The prompt should not be used to implement application control flow that can be handled deterministically in Python.

### `research_summarizer/api.py`

FastAPI adapter for the local web application.

The API should remain a thin layer around the core research workflow.

Current responsibilities:

- `/api/health`
- `/api/research`
- Input validation
- Local text-file upload handling
- Calling the research workflow
- Returning `SummaryResult`
- Mapping expected errors to HTTP responses
- Local development CORS configuration

Do not move research logic into the API layer.

### `research_summarizer/cli.py`

CLI interface for running research locally.

The CLI should call the same research core used by the API.

Do not duplicate research logic inside the CLI.

## Research Acquisition

Topic research uses Tavily.

Tavily is an evidence-acquisition tool, not an autonomous agent.

The integration should provide useful research evidence to the synthesis layer.

When implementing Tavily:

1. Keep the integration deterministic.
2. Preserve useful source metadata such as title and URL.
3. Prefer substantive result content over search-result snippets when Tavily provides it.
4. Do not invent source content.
5. Do not add an independent planning/re-planning stage.
6. Do not add multiple LLM calls merely to improve search queries.
7. Do not introduce a separate time service or runtime date mechanism.

The goal is not merely to replace the SerpApi API call.

The goal is to improve the quality of evidence supplied to the summarizer.

## LLM Call Policy

The normal research workflow should make exactly one LLM call.

```text
Evidence → LLM → Structured Result
```

Do not add:

- Planner calls
- Replanner calls
- Critic calls
- Repair calls
- Reflection loops
- Automatic retry-by-generation loops

unless a concrete product requirement demonstrates that the one-call design is insufficient.

Retries caused by transient API/network failures are different from additional reasoning stages and may be implemented when appropriate.

## No Autonomous Agent Loop

This project deliberately does NOT use:

- Planner
- Replanner
- LangGraph workflow orchestration
- `create_agent`
- autonomous tool loops
- recursive agent execution
- multi-stage agent state machines

Do not reintroduce these patterns without an explicit requirement.

The project should remain understandable by reading the main workflow from top to bottom.

## Time Handling

Do not add application-level time-awareness merely to make the model understand the current date.

Do not introduce:

- time MCP servers
- time APIs
- timezone services
- runtime date injection
- automatic query rewriting based on the current year

The LLM already receives normal user language and can interpret ordinary temporal expressions.

If a future feature has a genuine requirement for date-sensitive research, implement that requirement explicitly rather than adding a general-purpose time system.

## Error Handling

Errors should be handled at the appropriate layer.

Expected categories include:

- Invalid input
- Unsupported file type
- Invalid URL
- File reading errors
- Network errors
- Tavily API errors
- LLM API errors
- Invalid model output
- Pydantic validation errors

Do not hide failures by fabricating fallback research or summary content.

If evidence is insufficient, the final result should say so through `caveats`.

## Security

This is a local application, but basic input boundaries still matter.

Preserve the existing protections around:

- HTTP/HTTPS URL validation
- Local file type restrictions
- Upload size limits
- UTF-8 validation
- Local upload handling
- Path boundaries for local files

Do not weaken these protections for convenience.

When changing file or URL handling, test path traversal, unsupported schemes, and invalid input.

## Dependencies

Prefer the smallest dependency set that solves the problem.

Current stack:

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- `langchain-openai` for LLM access
- Tavily for web research
- Ruff for linting/formatting

`langchain-openai` is used as an LLM client integration.

Do not introduce the LangChain agent framework simply because `langchain-openai` is already installed.

Avoid adding frameworks when a small Python function is sufficient.

## Development Principles

When modifying this repository:

1. Read the existing implementation before changing it.
2. Preserve the current architecture unless the requested feature requires a structural change.
3. Prefer deterministic Python logic over agentic orchestration.
4. Prefer one clear data flow over abstractions that hide control flow.
5. Keep modules focused, but do not split files merely for the sake of having more files.
6. Do not add speculative features.
7. Do not add infrastructure that the local MVP does not need.
8. Make the smallest change that satisfies the requirement.
9. Update tests when behavior changes.
10. Update this file if the architecture materially changes.

## Things We Are Explicitly Not Building

Unless explicitly requested, do not add:

- Database
- Redis
- Celery
- RabbitMQ
- Background job infrastructure
- WebSockets
- SSE
- MCP servers
- Authentication
- User accounts
- Multi-user SaaS infrastructure
- Cloud deployment infrastructure
- Agent memory
- Vector database
- RAG pipeline
- Planner/Replanner
- Multi-agent systems
- Autonomous agent loops
- Time-awareness services

These may be useful in other products, but they are outside the scope of this project.

## Testing

Tests should focus on observable behavior.

Important areas include:

- Input dispatch
- URL validation
- Local file handling
- Tavily evidence conversion
- Evidence passed to the summarizer
- LLM response parsing
- Pydantic validation
- API input/output behavior
- Error handling

Tests should not depend on real external APIs unless a test is explicitly designed as an integration test.

Mock external services for deterministic unit tests.

When changing research acquisition, test the shape and quality of the evidence passed to the LLM rather than only testing that an API function was called.

## Definition of Done

A change is not complete merely because the code runs.

Before considering a feature complete:

1. The implementation matches the current architecture.
2. Existing tests still pass.
3. New behavior has appropriate tests.
4. No obsolete architecture remains in documentation.
5. No unnecessary dependencies or infrastructure were introduced.
6. External API failures are handled explicitly.
7. The resulting evidence is actually useful to the summarization layer.

For research-related changes, verify the complete flow:

```text
Input
  ↓
Evidence Acquisition
  ↓
Evidence
  ↓
One LLM Call
  ↓
Parsing
  ↓
SummaryResult
```

The primary goal is a small, reliable research summarizer—not a general-purpose autonomous agent framework.
