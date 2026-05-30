"""LangSmith trace inspector — print details for the most recent agent run.

Usage:
    python scripts/trace_inspect.py                # latest run
    python scripts/trace_inspect.py --limit 3      # last 3 runs
    python scripts/trace_inspect.py --run-id <id>  # specific run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (2 levels up from this script, or from cwd)
for candidate in [Path(__file__).resolve().parent.parent, Path.cwd()]:
    env_file = candidate / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        break

api_key = os.getenv("LANGSMITH_API_KEY")
project = os.getenv("LANGSMITH_PROJECT", "research-summarizer-agent")

if not api_key:
    print("LANGSMITH_API_KEY not set in .env", file=sys.stderr)
    sys.exit(1)


def fetch_trace(run_id: str | None = None, limit: int = 1) -> None:
    """Fetch and print run details."""
    from langsmith import Client

    client = Client(api_key=api_key, timeout_ms=30000)
    t0 = time.time()

    if run_id:
        runs = [client.read_run(run_id)]
    else:
        runs = list(client.list_runs(project_name=project, limit=limit, is_root=True))

    if not runs:
        print("No runs found.")
        return

    for i, r in enumerate(runs):
        rid = str(r.id)
        if limit > 1:
            print(f"\n{'='*60}")
            print(f"Run {i+1}/{len(runs)}")
            print(f"{'='*60}")

        print(f"Name:       {r.name}")
        print(f"Status:     {r.status}")
        print(f"Start:      {r.start_time}")
        if r.end_time:
            print(f"End:        {r.end_time}")
        if r.error:
            print(f"Error:      {r.error}")

        # Fetch all spans in this trace
        spans = list(client.list_runs(trace_id=r.trace_id))

        tools = [s for s in spans if s.run_type == "tool"]
        llms = [s for s in spans if s.run_type == "llm"]

        # Tool breakdown
        print(f"\nTool calls: {len(tools)}")
        tool_names: dict[str, int] = {}
        tool_errors: list[str] = []
        for t in tools:
            name = t.name or "?"
            tool_names[name] = tool_names.get(name, 0) + 1
            if t.status != "success":
                tool_errors.append(f"{name}: {t.status}")
        for name, count in sorted(tool_names.items()):
            print(f"  {count}× {name}")
        if tool_errors:
            print(f"  ERRORS: {', '.join(tool_errors)}")

        # LLM breakdown
        print(f"\nLLM calls: {len(llms)}")
        total_prompt = sum(l.prompt_tokens or 0 for l in llms)
        total_completion = sum(l.completion_tokens or 0 for l in llms)
        print(f"  Tokens:   {total_prompt + total_completion} total")
        print(f"            {total_prompt} prompt + {total_completion} completion")

        elapsed = time.time() - t0
        print(f"\nFetched {len(spans)} spans in {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect LangSmith agent traces")
    parser.add_argument("--limit", type=int, default=1, help="Number of recent runs to show")
    parser.add_argument("--run-id", type=str, help="Specific run UUID to inspect")
    args = parser.parse_args()

    if args.run_id:
        fetch_trace(run_id=args.run_id)
    else:
        fetch_trace(limit=args.limit)


if __name__ == "__main__":
    main()
