"""Command-line interface for the Research Summarizer Agent."""

from __future__ import annotations

import argparse

from research_summarizer.agent import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Research Summarizer Agent.")
    parser.add_argument(
        "request",
        nargs="*",
        help="Research topic, URL, or instruction. If omitted, you will be prompted.",
    )
    args = parser.parse_args()

    request = " ".join(args.request).strip()
    if not request:
        request = input("Research request: ").strip()

    if not request:
        raise SystemExit("No research request provided.")

    print(run_agent(request))


if __name__ == "__main__":
    main()
