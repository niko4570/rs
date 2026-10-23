"""Check fixtures offline, or replay them through one synthesis call each."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from research_summarizer.evidence import format_synthesis_evidence
from research_summarizer.models import SourceContent
from research_summarizer.parser import ParseError, parse_synthesis
from research_summarizer.prompts import SUMMARIZE_SYSTEM_PROMPT
from research_summarizer.summarizer import build_model, summarize_evidence

CASES = Path(__file__).with_name("cases.json")


def prepare(case: dict) -> tuple[str, set[str], dict[str | None, str]]:
    """Recreate the existing synthesis boundary from frozen acquired evidence."""
    items = case["items"]
    if not items:
        return case["note"], set(), {}
    citations: dict[str | None, str] = {}
    for item in items:
        url = item["url"]
        citations[url] = "\n".join(filter(None, [citations.get(url), item["content"]]))
    urls = {item["url"] for item in items if item["url"] is not None}
    return format_synthesis_evidence(source_registry(case)), urls, citations


def source_registry(case: dict) -> dict[str, SourceContent]:
    return {
        f"S{index}": SourceContent(title=item["title"], url=item["url"], content=item["content"])
        for index, item in enumerate(case["items"], start=1)
    }


def load_cases() -> list[dict]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert 10 <= len(cases) <= 20
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["route"] in {"search", "url", "file"}
        assert case["request"].strip() and case["must_cover"] and case["must_avoid"]
        assert case["items"] or case["note"].strip()
        if case["route"] != "search":
            assert len(case["items"]) <= 1
        for item in case["items"]:
            assert item["content"].strip()
            if case["route"] == "file":
                assert item["url"] is None
            else:
                assert item["url"].startswith("https://example.com/")
        prepare(case)
    return cases


def replay(case: dict, model) -> dict:
    evidence, _, _ = prepare(case)
    row = {"id": case["id"], "raw": None, "result": None, "status": "call_error",
           "review": {"coverage": None, "support": None, "caveats": None,
                      "notes": ""}}
    start = time.perf_counter()
    try:
        row["raw"] = summarize_evidence(case["request"], evidence, model)
        row["result"] = parse_synthesis(row["raw"], source_registry(case)).model_dump()
        row["status"] = "valid"
    except ParseError as exc:
        row.update(status="invalid", error=str(exc))
    except Exception as exc:  # noqa: BLE001 -- keep failed cases in the report, without retry
        # Provider errors can contain credentials; retain the type only.
        row["error"] = type(exc).__name__
    row["seconds"] = round(time.perf_counter() - start, 3)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call configured LLM (paid API).")
    parser.add_argument("--output", type=Path, help="New JSON report path; never overwritten.")
    args = parser.parse_args()
    cases = load_cases()
    if not args.live:
        print(f"Checked {len(cases)} frozen cases offline; no API calls.")
        return 0
    if args.output is None:
        parser.error("--live requires --output")
    # Reserve the report before making paid calls; reject existing paths.
    with args.output.open("x", encoding="utf-8") as output:
        model = build_model().model_copy(update={"temperature": 0, "max_retries": 0})
        # Also disable retries on the underlying OpenAI clients.
        model.client._client.max_retries = 0
        model.async_client._client.max_retries = 0
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        report = {
            "created": datetime.now(UTC).isoformat(),
            "revision": revision,
            "suite_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
            "prompt_sha256": hashlib.sha256(SUMMARIZE_SYSTEM_PROMPT.encode()).hexdigest(),
            "code_sha256": {
                name: hashlib.sha256(
                    (CASES.parent.parent / "research_summarizer" / name).read_bytes()
                ).hexdigest()
                for name in ("evidence.py", "summarizer.py", "parser.py", "models.py")
            },
            "model": model.model_name,
            "output_format": os.getenv("OPENAI_OUTPUT_FORMAT", "json_object"),
            "temperature": 0, "sdk_retries": 0,
            "results": [],
        }
        for case in cases:
            row = replay(case, model)
            report["results"].append(row)
            # Persist each completed call so an interrupted run remains reviewable.
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
            print(f"{case['id']}: {row['status']}", flush=True)
    valid = sum(row["status"] == "valid" for row in report["results"])
    print(f"Mechanical validation: {valid}/{len(cases)}. Semantic review still required.")
    return 0 if valid == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
