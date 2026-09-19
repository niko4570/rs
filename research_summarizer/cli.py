"""Command-line interface for the Research Summarizer Agent."""

from __future__ import annotations

import argparse
import sys

from research_summarizer.agent import ProgressCallback, run_agent
from research_summarizer.parser import ParseError


def _format_result(result) -> str:
    """Format a SummaryResult for CLI display."""
    lines = ["Summary:"]
    for bullet in result.summary_bullets:
        lines.append(f"  - {bullet}")

    lines.append("")
    lines.append(f"Key details: {result.key_details}")

    if result.sources:
        lines.append("")
        lines.append("Sources:")
        for source in result.sources:
            title = source.title or source.url
            lines.append(f"  - {title} ({source.url})")

    if result.caveats:
        lines.append("")
        lines.append("Caveats:")
        for caveat in result.caveats:
            lines.append(f"  - {caveat}")

    return "\n".join(lines)


def _make_progress_printer() -> ProgressCallback:
    """Return a callback that prints progress to stderr."""
    def _printer(stage: str, message: str) -> None:
        # Skip some internal stages for cleaner output
        if stage in ("parse",):
            return
        print(f"[{stage.upper()}] {message}", file=sys.stderr, flush=True)
    return _printer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Research Summarizer Agent.")
    parser.add_argument(
        "request",
        nargs="*",
        help="Research topic, URL, or instruction. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args()

    request = " ".join(args.request).strip()
    if not request:
        request = input("Research request: ").strip()

    if not request:
        raise SystemExit("No research request provided.")

    progress_cb = None if args.quiet else _make_progress_printer()

    try:
        result = run_agent(request, on_progress=progress_cb)
        print(_format_result(result))
    except ParseError as e:
        print(f"Error: Could not produce a valid structured result.\n{e}", file=sys.stderr)
        if e.raw_text:
            print(f"\nRaw output (unparsed):\n{e.raw_text[:1000]}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
