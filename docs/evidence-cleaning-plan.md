# Plan: Info-Preserving Cleaning of Tavily Search Evidence

Status: proposed — pending feasibility review
Owner: research_summarizer
Scope: `research_summarizer/evidence.py` (search path), tests, no API/contract change

## Feasibility verdict (read this first)

**Verdict: feasible, low-risk if phased as L0 → L1 → L2.** The work is confined to
`research_summarizer/evidence.py`, adds no dependencies, and uses pure functions that are easy
to unit-test and to gate behind a flag. The main risk is heuristic over-trimming in L1/L2, which
is why Phase 1 (L0) is near-zero risk and every phase includes a fallback-to-raw safety valve.
Effort estimate: L0 ≈ 0.5 day, L1 ≈ 1 day, L2 ≈ 1–2 days, all with tests.

## 1. Problem statement (measured, not assumed)

Tavily `raw_content` is polluted by site chrome that consumes the fixed evidence budget,
crowding out article text. Figures below are from a real trace
(`research-summarizer-agent`, run `01a110cf-6bd0-74c0-9014-c0ca1368d45b`):

| Source | chars | image markup | empty links | real prose in budget |
|---|---|---|---|---|
| S1 Requesty | 6000 | 290 | 0 | 4216 (18 lines) |
| S2 MindStudio | 6000 | 148 | 0 | ~0 (all cookie widget) |
| S3 LangChain | 6000 | **1579** | 219 | **470 (3 lines)** |
| S4 CBInsights | 1438 | 128 | 0 | 593 (off-topic) |

Root cause of the earlier caveats ("article truncated, could not answer Noul/pricing"):
boilerplate, not insufficient evidence. Cleaning is therefore framed as **recall recovery**,
not token reduction.

## 2. Goals / Non-goals

**Goals**
- Recover article text currently lost to `MAX_SEARCH_CONTENT_CHARS` truncation.
- Remove only content that cannot be cited as text evidence.
- Never make evidence worse than today (guaranteed by fallback).

**Non-goals**
- Reducing prompt/reasoning tokens (measured: reasoning = 3938/5345 output tokens; unaffected).
- Re-tuning Jev thresholds in this plan.
- Fetching pages ourselves or changing the evidence contract (`title/url/content`).

## 3. Design principles (the "don't waste needed information" guarantee)

1. **Only strip non-text markup** when possible (images/empty links cannot be cited).
2. **Edge-trim, never middle-delete.** Nav is removed only before article start / after article
   end; the article region is preserved verbatim.
3. **No keyword/length-based global deletion** — the S2 trace proved cookie text looks like
   prose (4481 "prose" chars, all boilerplate), and S4 showed short lines can be data.
4. **Fallback-to-raw safety valve** on every phase: if cleaned output is empty, below an
   absolute floor, or shrinks past a ratio, return the original text.
5. **Single cleaning point** before `EvidenceItem` construction so Jev, synthesis, and `excerpt`
   validation all see the same text.

## 4. Proposed changes

### Phase 1 — L0: lossless structural cleaning (recommended first)

Add in `evidence.py`:

```python
def _strip_markdown_noise(text: str) -> str:
    """Remove markdown images and empty links; never removes text."""
    # order: linked image -> image -> empty link, loop until stable
    #   [![alt](img)](href) -> ""
    #   ![alt](img)         -> ""
    #   [](href)            -> ""
```

- Apply inside `_select_search_content` (or immediately after it in `search_web_items`) before
  `_clean_text`.
- Also consider applying to the `fetch_url` body for consistency (open question below).
- Add `MIN_CLEAN_CONTENT_CHARS` floor and `_apply_cleaning_with_fallback(raw, cleaner)` helper.

**Expected effect:** recovers ~2.1 KB per run; S3 gains ~30% of its budget back.
Information loss ≈ 0.

### Phase 2 — L1: boundary-based nav/footer trimming

Add:

```python
def _trim_boilerplate_edges(text: str) -> str:
    """Trim leading nav and trailing footer; preserve the article region."""
```

- Article start = first heading line, or first prose line (`len >= 60`, link density `< 0.3`)
  that is followed by another prose/heading line within k lines.
- Article end = last prose line; trim trailing link-dense lines after it.
- Keep everything between start and end unchanged.

**Expected effect:** S3 recovers ~29 nav lines. Risk low but heuristic; flag-gated.

### Phase 3 — L2: conservative consent/embed handling

- Detect a **contiguous run at the start** that matches ≥2 consent markers (`cookie`, `consent`,
  `privacy`, `accept all`, `reject all`, `We value your privacy`); remove that run only.
- Do **not** remove social embeds wholesale — the S1 trace contains a citable quote inside a
  tweet; rely on L0 image stripping to shrink them and keep text lines.

**Expected effect:** recovers S2's real article. Highest false-positive risk; keep behind a flag.

### Configuration

```python
EVIDENCE_CLEANING = os.getenv("EVIDENCE_CLEANING", "structure")  # off | structure | edges | all
MIN_CLEAN_CONTENT_CHARS = 800
CLEANING_FALLBACK_RATIO = 0.35  # keep raw if cleaned < 35% of raw
```

## 5. Contract & architecture impact

- `evidence.py` remains the sole owner of acquisition and text shaping — consistent with
  `AGENTS.md`.
- No change to `EvidenceItem`, `format_evidence`, API, CLI, or `SummaryResult`.
- **Behavioral change to Jev**: cleaned content may change `relevant`/`usable_evidence`
  (e.g., S2 may become selectable). This is intended but must be covered by tests and observed.
- `excerpt` validation stays valid: the model only sees cleaned text.

## 6. Test plan

Unit (pure functions):
- `_strip_markdown_noise`: linked image removed; standalone image removed; empty link removed;
  prose with an inline link preserved; reference-list links preserved.
- `_trim_boilerplate_edges`: leading nav removed, article intact; no middle line ever dropped;
  trailing footer removed.
- Fallback valve: over-cleaning / empty result returns raw.

Integration (`search_web_items`, mocked Tavily):
- Fixtures built from real S1/S2/S3 fragments; assert article sentences present and
  image/nav/cookie text absent.
- Assert cleaned content contains article text that the raw truncated content did not
  (recall-recovery assertion).
- Assert `EVIDENCE_CLEANING=off` reproduces current behavior exactly.

Regression:
- Existing `tests/test_tools.py`, `tests/test_jev.py`, `tests/test_agent.py` still pass.
- Full suite + Ruff green.

## 7. Rollout & rollback

- Ship L0 only, default `EVIDENCE_CLEANING=structure`.
- Add a trace attribute (e.g., `cleaned_chars`, `raw_chars`) to the `search_web` run for
  LangSmith observability.
- Rollback = set `EVIDENCE_CLEANING=off` (no code revert needed).

## 8. Risks & open questions for reviewer

| Risk | Mitigation |
|---|---|
| L1/L2 over-trim real content | edge-only trimming + fallback + flag |
| Jev judgments shift | keep thresholds, monitor traces, add tests |
| S2 cookie block not detected | accept as limitation; L0 already removes its image noise |

Open questions:
1. Should cleaning also apply to `fetch_url` bodies, or search only?
2. Are `MIN_CLEAN_CONTENT_CHARS=800` / `FALLBACK_RATIO=0.35` acceptable defaults?
3. Should we re-validate Jev thresholds after cleaning, or keep them fixed for now?
4. Do you want a `docs/` design note committed alongside the code?

## 9. Acceptance criteria

- L0/L1 reduce boilerplate and **increase surviving article characters** in trace fixtures.
- No test regresses; full suite + Ruff pass.
- Fallback valve proven by a dedicated test.
- A real end-to-end run shows more article content (e.g., the previously missing Noul/pricing
  details become available).
