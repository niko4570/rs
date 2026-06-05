# Update — Feasibility-Adjusted Agent Architecture Roadmap

## Current State

The project is a beginner-friendly LangChain research summarizer agent. It currently uses:

- `create_agent()` as the main agent loop
- Three tools: `search_web`, `fetch_url`, and `read_text_file`
- Per-run fetch caching and URL normalization
- Stale-year correction inside `search_web`
- A CLI wrapper around `run_agent()`
- Pytest tests with mocked LLM behavior

The current architecture is good for a first agent. The main limitation is that the output contract still lives mostly in the system prompt. The code asks the model to produce sections like Summary, Key details, Sources, and Caveats, but the code does not yet parse or verify those sections before returning them.

## Feasibility Verdict

The plan is feasible, but it should be implemented in smaller learning-focused steps.

The original direction is correct:

1. Move from unstructured text to typed results.
2. Add validation before returning answers.
3. Track source state in code instead of relying only on prompt memory.
4. Move gradually from a black-box agent loop to an explicit Python-controlled workflow.
5. Add critique/evaluation only after the basics are measurable.

The risky part is trying to jump directly from the current `create_agent()` setup to a full planner, replanner, executor, validator, and critic system. That would be a lot of framework code before proving that the smaller improvements actually help.

The revised roadmap below keeps the same architecture direction, but splits it into safer milestones.

---

## Design Rules

1. **Typed output before advanced control flow.**
   The first major improvement should be a machine-readable `SummaryResult`, not a planner.

2. **Use Pydantic models for LLM-facing structured output.**
   Pydantic works better than dataclasses for `with_structured_output()`, JSON validation, and clear error reporting.

3. **Track run state explicitly.**
   Validation needs to know what URLs were searched, fetched, failed, or read from local files.

4. **Use tools directly when the action is already known.**
   If code has already decided to fetch a specific URL or read a specific file, call the tool directly. Do not ask an LLM agent to make a deterministic tool call.

5. **Add critique only after validation and benchmark prompts exist.**
   A critic without structured evidence and baseline results can create fake confidence.

---

## Phase 1a: Structured Output Without Retry

**Goal:** Convert the final model answer into a typed result that code can inspect.

### Output Models

Use Pydantic models:

```python
from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str | None = None
    url: str
    snippet_used: str | None = None


class SummaryResult(BaseModel):
    summary_bullets: list[str] = Field(min_length=4, max_length=7)
    key_details: str
    sources: list[Source]
    caveats: list[str]
```

### Parsing Strategy

Start with a conservative parser flow:

1. Run the current `create_agent()` flow.
2. Take the final message content.
3. Ask the model to convert that answer into JSON matching `SummaryResult`.
4. Validate with `SummaryResult.model_validate_json()` or `model_validate()`.
5. If parsing fails, return a clear parse failure message for now.

Do not add retry yet. First make parsing observable and testable.

### Code Changes

- Add `models.py` for `Source` and `SummaryResult`.
- Add `parser.py` for final-answer-to-JSON parsing.
- Keep `run_agent()` returning text for CLI compatibility at first.
- Add a separate helper such as `run_agent_structured()` for tests and internal use.

### Tests

- Parses valid JSON into `SummaryResult`.
- Rejects too few or too many summary bullets.
- Rejects malformed source objects.
- Handles parser failure cleanly.

---

## Phase 1b: Validation

**Goal:** Detect weak or hallucinated final answers before delivery.

### Run State

Validation needs source state. Add a lightweight model:

```python
class RunState(BaseModel):
    searched_urls: set[str] = set()
    fetched_urls: set[str] = set()
    failed_fetch_urls: set[str] = set()
    read_files: set[str] = set()
```

This can start simple. It does not need to replace every tool implementation immediately. The first version can record state in wrapper functions around tool calls or by parsing tool outputs in tests.

### Validation Report

```python
class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: str = "error"


class ValidationReport(BaseModel):
    passed: bool
    issues: list[ValidationIssue]
```

### Checks

1. **Bullet count:** enforced by Pydantic.
2. **Source integrity:** every cited URL must appear in searched or fetched URLs.
3. **Failed-source citation:** sources that returned `[FETCH_ERROR]` must not be cited as successful evidence.
4. **Generic caveats:** reject empty or generic caveats such as "may be incomplete" without a specific reason.
5. **Coverage warning:** if several pages were fetched but only one was cited, warn rather than fail at first.

### Code Changes

- Add `validation.py`.
- Add unit tests before wiring validation into the CLI.
- Keep validation reports visible in tests and optionally in debug output.

### Tests

- Catches hallucinated source URL.
- Catches citation of failed fetch.
- Catches generic caveat.
- Allows a valid result.
- Emits a warning for low source coverage.

---

## Phase 1c: One Formatting Retry

**Goal:** If the final answer is structurally invalid, retry only the formatting/parsing step.

Do not rerun the full research agent. Re-running the full agent would waste time and may produce different tool behavior.

Flow:

```python
raw_answer = run_current_agent(request)
for attempt in range(2):
    result = parse_summary(raw_answer, previous_failure=last_error)
    if result is valid:
        return result
return failure_report
```

This teaches an important agent-building pattern: recover from bad model output with a focused repair call, not by restarting the whole task.

---

## Phase 2: Explicit Research Loop

**Goal:** Move workflow control from the black-box agent loop into readable Python code.

This phase should happen only after Phase 1 is passing tests.

### Revised Architecture

```python
def run_agent_structured(request: str) -> SummaryResult:
    state = RunState()

    plan = plan_research(request)
    evidence = []

    for step in plan.steps:
        step_result = execute_step_directly(step, state)
        evidence.append(step_result)

        if step_result.failed and step_result.retryable:
            replacement = replan_step(step, step_result, plan, state)
            if replacement:
                evidence.append(execute_step_directly(replacement, state))

    draft = summarize_evidence(request, evidence)
    result = parse_summary(draft)
    report = validate_summary(result, state)

    if not report.passed:
        result = repair_summary(result, report, evidence)

    return result
```

### Key Change From Original Plan

Do not use `create_agent()` for single-turn deterministic tool execution.

If a step is:

```python
ResearchStep(action="fetch", input="https://example.com")
```

then Python should call `fetch_url` directly. The LLM should help with planning, summarizing, and possibly replanning, not with obvious tool dispatch.

### Plan Model

```python
class ResearchStep(BaseModel):
    action: Literal["search", "fetch", "read_file"]
    input: str
    purpose: str


class ResearchPlan(BaseModel):
    steps: list[ResearchStep]
    comparison_strategy: str | None = None
```

### Code Changes

- Add `planner.py`.
- Add `executor.py`.
- Add `state.py`.
- Keep old `build_agent()` available while the new loop is being built.
- Let `cli.py` keep the same interface.

### Tests

- A URL request creates a fetch step.
- A local file request creates a read-file step.
- A topic request creates a search step.
- Failed fetch can trigger one replacement step.
- Replanning is bounded and cannot loop forever.

---

## Phase 2.5: Progress UX

**Goal:** Make long agent runs understandable from the CLI.

This should come before self-critique because it improves learning and debugging immediately.

Examples:

```text
Planning research...
Searching: latest AI regulation in China
Fetching: https://...
Fetch failed: HTTP 403, trying next result
Summarizing 3 evidence items...
Validating output...
```

This teaches callbacks, streaming, and run observability without changing the agent's intelligence.

---

## Phase 3: Critique and Revise

**Goal:** Improve answer quality by reviewing the draft against evidence before delivery.

Only start this after:

- Structured output exists.
- Validation exists.
- `RunState` exists.
- A benchmark prompt set exists.
- Phase 2 behavior is stable.

### Critique Model

```python
class CritiqueResult(BaseModel):
    source_fidelity: float
    source_diversity: float
    caveat_specificity: float
    completeness: float
    overall_score: float
    gaps: list[str]
```

### Bounded Loop

```python
draft = summarize_evidence(request, evidence)
best_score = 0.0

for attempt in range(2):
    critique = critique_output(draft, evidence, state)
    if critique.overall_score <= best_score:
        break
    if critique.overall_score >= 0.8:
        break
    best_score = critique.overall_score
    draft = revise_output(draft, critique, evidence)
```

### Important Constraint

Critique should not replace validation. Validation is a deterministic gate. Critique is a quality-improvement step.

---

## Benchmark Prompts

Use the same prompts across phases:

1. "Summarize the latest news about AI regulation in China"
2. "Compare React 19 vs Vue 4 for state management"
3. "https://en.wikipedia.org/wiki/Attention_(machine_learning)"
4. "What caused the SVB collapse?"
5. "Research nonexistent_topic_xyz_123"
6. "Explain quantum computing for a 12-year-old"
7. "Latest breakthroughs in fusion energy 2026"
8. "Summarize README.md"
9. "Are we in an AI bubble? Compare 2024 vs 2026 arguments"
10. "What's new in Python 3.14?"

For each run, record:

- Final answer quality
- Parse success
- Validation issues
- Tool call count
- Runtime
- Whether the answer cited unavailable or hallucinated sources

---

## Success Criteria

| Phase | Success Criteria |
| --- | --- |
| 1a | Final answers parse to `SummaryResult` on most benchmark prompts. Parser failures are clear and test-covered. |
| 1b | Validator catches hallucinated sources, failed-source citations, and generic caveats in unit tests. |
| 1c | One formatting retry repairs common structural failures without rerunning research. |
| 2 | The explicit loop can run search/fetch/read-file plans, update run state, and avoid unbounded replanning. |
| 2.5 | CLI shows useful progress for long runs. |
| 3 | Critique finds real gaps and improves benchmark answers often enough to justify its latency cost. |

---

## Recommended Implementation Order

1. Create a branch: `phase-1-structured-output`.
2. Add Pydantic models.
3. Add parser tests.
4. Add parser implementation.
5. Add validation tests.
6. Add validation implementation.
7. Add `RunState`.
8. Wire structured output behind a helper without breaking the current CLI.
9. Add one formatting retry.
10. Run benchmark prompts and record results.
11. Only then start Phase 2.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| DeepSeek does not support `with_structured_output()` reliably | Structured output may fail | Use raw text plus JSON parser prompt as the first implementation. |
| Validation lacks enough source state | False positives or weak checks | Add `RunState` before strict source validation. |
| Phase 2 creates too much code too early | Learning slows down | Finish Phase 1a/1b/1c first. |
| Replanning loops forever | Long or stuck runs | Add max replacements per step and max total steps. |
| Critique adds latency without quality gains | Slower agent | Benchmark before and after; skip critique for simple URL/file summaries. |
| CLI output changes break current usage | Bad developer experience | Keep `run_agent()` returning text; add structured helpers separately first. |

---

## Final Recommendation

Start with Phase 1a.

For learning agent-building, the most valuable next concept is not multi-agent design or a complex planner. It is learning how to turn model output into typed state, validate that state, and make the program react when the model output is not good enough.

Once that works, the planner and critic will be much easier to build correctly.
