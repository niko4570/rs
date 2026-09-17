# Research Summarizer Agent

A minimal, local-only research summarizer that accepts a topic, URL, or local text file and returns a structured summary with key details, sources, and caveats.

## Features

- **Web Search**: Searches Google through SerpApi for topic research
- **URL Fetching**: Reads and summarizes web pages
- **Local File Reading**: Processes local `.txt` or `.md` files
- **LangSmith Tracing**: Ready for tracing and debugging with LangSmith
- **Multiple LLM Support**: Compatible with OpenAI and DeepSeek models

## How it works

The workflow is intentionally minimal:

```text
request ──► dispatch ──► one tool ──► one LLM call ──► SummaryResult
              │            │              │
              │            │              └─ synthesize JSON (summary, key details,
              │            │                 sources, caveats)
              │            └─ URL → fetch, .txt/.md file → read_file,
              │               anything else → search (SerpApi)
              └─ deterministic, no LLM planning
```

Each request makes exactly one LLM call.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/research-summarizer-agent.git
   cd research-summarizer-agent
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install the package:
   ```bash
   pip install -e .
   ```

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

You also need a SerpApi key for web search:

```bash
SERPAPI_API_KEY=...
```

## Usage

Run the agent from the command line:

```bash
research-agent "Summarize the latest news about AI in 2026"
```

Or with a URL:

```bash
research-agent "https://example.com/article"
```

Or with a local file:

```bash
research-agent "/path/to/your/file.md"
```

If no argument is provided, you'll be prompted to enter a research request.

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

## License

[MIT License](LICENSE)

This folder already had a `deepseek_api` variable, so the agent also accepts that
name for convenience.

For Google search through SerpApi:

```bash
SERPAPI_API_KEY=...
```

## Optional LangSmith Tracing

Add these to `.env` if you want to see traces, tool calls, latency, and errors in
LangSmith:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=research-summarizer-agent
```

## Run

```bash
python -m research_summarizer.cli "Research and summarize LangChain vs LangGraph for beginners"
```

You can also pass a URL:

```bash
python -m research_summarizer.cli "Summarize https://docs.langchain.com/oss/python/langchain/overview"
```

Or a local file:

```bash
python -m research_summarizer.cli "Summarize README.md"
```

## Local Web API

A minimal FastAPI layer exposes the same agent core over HTTP:

```bash
pip install -e .
uvicorn research_summarizer.api:app --host 127.0.0.1 --port 8000 --reload
```

Endpoints:

```text
GET  /api/health
POST /api/research   (multipart/form-data)
```

`POST /api/research` accepts either:

- `input_type=url` with a `url` field (http/https)
- `input_type=file` with a `file` upload (`.txt` or `.md`)

Uploaded files are written to `.uploads/` (gitignored) and read by the
agent's existing local-file tool. The response is the structured
`SummaryResult` shape:

```json
{
  "summary_bullets": ["..."],
  "key_details": "...",
  "sources": [{"title": "...", "url": "...", "snippet_used": null}],
  "caveats": ["..."]
}
```

CORS is enabled for the local Vite dev origin (`http://localhost:5173`).

## Normal Development Workflow

1. Start with one clear job: research and summarize source material.
2. Keep the smallest useful tools: search, fetch URL, read file.
3. Dispatch deterministically: URL → fetch, file → read, topic → search.
4. Use LangSmith tracing while testing.
5. Save 5-10 test prompts and check whether the answer is accurate, cited, and concise.
