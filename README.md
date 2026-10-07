# Research Summarizer Agent

A minimal, local-only research summarizer that accepts a topic, URL, or local text file and returns a structured summary with key details, sources, and caveats.

## Features

- **Web Search**: Searches the web through Tavily for topic research
- **Evidence Selection**: Uses TypeSafe Jev to rank and keep the most relevant search sources
- **URL Fetching**: Reads and summarizes web pages
- **Local File Reading**: Processes local `.txt` or `.md` files
- **LangSmith Tracing**: Ready for tracing and debugging with LangSmith
- **Multiple LLM Support**: Compatible with OpenAI and DeepSeek models

## How it works

The workflow is intentionally minimal:

```text
request ──► dispatch ──► evidence ──► [Jev selection] ──► one LLM call ──► SummaryResult
              │             │              │                   │
              │             │              │                   └─ synthesize JSON (summary,
              │             │              │                      key details, sources, caveats)
              │             │              └─ search only: TypeSafe Jev ranks sources,
              │             │                 code keeps the top 3
              │             └─ URL → fetch, .txt/.md file → read_file,
              │                anything else → search (Tavily)
              └─ deterministic, no LLM planning
```

Each request makes exactly one synthesis LLM call. Topic searches also make
one Jev judgment call per source (TypeSafe) before synthesis; URL and file
requests skip Jev.
The API keeps its explicit input type when dispatching; the CLI infers a route
from free-form input. Returned source URLs are checked against the evidence
actually sent to synthesis. Local-file results have no web source URLs.
Each summary bullet includes a citation with a short excerpt copied from its
source. The parser checks that every bullet has a citation when evidence is
available, and that each excerpt occurs in the cited source. For local files,
the citation identifies the file without adding a web URL. The UI expands
citations inline; the CLI prints them beneath each bullet.

## Installation

Requires Python 3.11+, Node.js/npm, and Make.
The Makefile uses POSIX shell commands and `.venv/bin/` paths;
on Windows, use WSL.

```bash
git clone https://github.com/niko4570/rs.git
cd rs
make install
```

`make install` creates `.venv` and installs the Python package in editable
mode plus frontend dependencies. Configure `.env` as described below before
running a research request.

## Configuration

Create a `.env` file in the project root with your API keys:

For OpenAI:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

For DeepSeek:

```bash
DEEPSEEK_API_KEY=...
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
```

You also need a Tavily key for web search:

```bash
TAVILY_API_KEY=tvly-...
```

And a TypeSafe key for Jev evidence selection on topic searches:

```bash
TYPESAFE_API_KEY=...
# Optional; defaults to jev-latest
TYPESAFE_MODEL=jev-latest
```

If `TYPESAFE_API_KEY` is unset or Jev is unavailable, search evidence is used
as-is (selection is skipped) rather than failing the request.

### Optional LangSmith Tracing

Add these to `.env` if you want to see traces, tool calls, latency, and errors in
LangSmith:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=research-summarizer-agent
```

## Usage

Run these commands from the repository root after installation and configuration.

### CLI

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Pass a topic, URL, or a local file within the project root:

```bash
research-agent "Summarize the causes of the Opium War"
research-agent "https://example.com/article"
research-agent "./README.md"
```

`python -m research_summarizer.cli` is an alternative to `research-agent`.
Without an argument, the CLI prompts for a request.

### Web app

Start the backend and frontend together:

```bash
make dev
```

Open http://localhost:5173. The backend runs at http://127.0.0.1:8000.
Press Ctrl+C to stop both servers.

To run them separately, use two terminals:

```bash
# Terminal 1, from the repository root
make backend
```

```bash
# Terminal 2, from the repository root
make frontend
```

These targets run the following commands respectively:

```bash
.venv/bin/uvicorn research_summarizer.api:app --host 127.0.0.1 --port 8000 --reload
(cd frontend && npm run dev)
```

The frontend uses `VITE_API_BASE_URL`, defaulting to
`http://127.0.0.1:8000`. To override it, copy `frontend/.env.example`
to `frontend/.env` and edit the value.

## Local Web API

A minimal FastAPI layer exposes the same agent core over HTTP.
Start it with `make backend` (see Usage).

Endpoints:

```text
GET  /api/health
POST /api/research   (multipart/form-data)
```

`POST /api/research` accepts one of:

- `input_type=topic` with a `query` field (a research question)
- `input_type=url` with a `url` field (http/https)
- `input_type=file` with a `file` upload (`.txt`, `.md`, or `.markdown`)

Uploaded files are written to `.uploads/` (gitignored) and read by the
agent's existing local-file tool. The response is the structured
`SummaryResult` shape:

```json
{
  "summary_bullets": ["..."],
  "key_details": "...",
  "sources": [{"title": "...", "url": "...", "snippet_used": null}],
  "citations": [{"bullet_index": 0, "source_url": "...", "excerpt": "..."}],
  "caveats": ["..."]
}
```

CORS is enabled for the local Vite dev origin (`http://localhost:5173`).

## Known Issues

- Topic research runs a single web search (no multi-source cross-checking)
- Failed URL fetches and search errors are passed to the LLM as evidence, so
  they are reflected in the summary rather than retried
- No explicit runtime limits
- DeepSeek v4 models require disabling thinking mode

## Development

This project uses:

- Python 3.11+
- `langchain-openai` for LLM access (no LangChain agent framework)
- Pydantic for structured output
- FastAPI + Uvicorn for the local API
- Ruff for linting

Install the additional tools needed for tests and linting:

```bash
.venv/bin/python -m pip install -e ".[dev]" ruff
```

`make install` does not install the optional development dependencies,
and Ruff is not currently included in the `dev` extra.

```bash
make test      # run backend tests
make lint      # lint Python sources and tests with Ruff
make build     # type-check and production-build the frontend
make check     # run lint, backend tests, and frontend build
```

Run `make help` to list all targets.

## License

[MIT License](LICENSE)
