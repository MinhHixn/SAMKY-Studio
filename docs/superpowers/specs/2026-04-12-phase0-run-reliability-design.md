# Phase 0 Run Reliability Design (Event Integrity + 429 Resilience)

## Problem

The 1-model test for one event only currently fails for two concrete reasons:

1. Non-benchmark taxonomy records (for example `short`, `medium`) are being interpreted as runnable events, which then fail B/C injection lookup with `Missing injection event_id`.
2. OpenRouter free-tier rate limits (`429`) cause evaluator failures before units complete.

Goal: make the 1-model, one-event test reliable for the existing one-LLM-at-a-time A/B/C workflow, while preserving current benchmark semantics.

## Scope

In scope:

- Event selection integrity for benchmark runs.
- Injection coverage validation for selected events.
- No-cap wait-and-retry behavior for rate-limit (`429`) responses.
- Targeted test updates for parser, preflight validation, and retry path.

Out of scope:

- Changing benchmark methodology (A/B/C logic, scoring formulas, rubric contract).
- Changing provider/model choices.
- Refactoring unrelated benchmark modules.

## Approach Options Considered

### Option 1 (Selected): Strict preflight + sanitized parsing + no-cap 429 wait

- Tighten event extraction to only include real event records.
- Ensure selected run events are injection-covered for B/C before execution.
- Retry `429` with wait-until-reset semantics and no per-unit cap.

Pros: deterministic run matrix, no silent skips, aligns with reproducible benchmark execution.
Cons: runs can block for long periods when provider is heavily throttled.

### Option 2: Soft runtime skipping for missing injections

- Keep loose parsing and skip invalid units dynamically.

Pros: fast progress.
Cons: incomplete condition matrix and biased summaries.

### Option 3: Data-only patch workflow

- Keep code mostly unchanged and manually patch source JSON each run.

Pros: low code churn.
Cons: brittle, non-repeatable, high operator burden.

## Selected Design

## 1) Event Integrity Pipeline

- Update raw event collection logic so taxonomy/meta dictionaries are not converted into synthetic events.
- Preserve support for real event records (`id`/`event_id` + forecast fields), while rejecting accidental key/value mappings that are not event-shaped.
- Build the condition matrix only from sanitized event IDs.

### Behavioral result

- `short`/`medium` will not appear in `event_ids` or run units.
- All run units correspond to intended benchmark events.

## 2) Injection Coverage Preflight

- Before orchestration starts, validate the selected event set against injection bank coverage for B/C.
- If any selected event lacks B/C payloads, fail in preflight with a clear error listing missing event IDs.
- Continue enforcing existing loader strictness during config building.

### Behavioral result

- No more mid-run `Missing injection event_id` surprises.
- Early, explicit failure when dataset/injection bank drift exists.

## 3) 429 Resilience (No-Cap Wait)

- Extend LLM retry behavior to treat rate-limit responses as waitable rather than terminal.
- When reset metadata is available, wait until reset boundary; otherwise use exponential backoff + jitter.
- Keep retrying without a per-unit timeout cap (as requested), while preserving existing behavior for non-retryable errors.

### Behavioral result

- Free-tier throttling pauses the run instead of producing `evaluation_failed` due only to temporary quota windows.
- Long runs remain eventually-progressing under intermittent provider limits.

## 4) Observability and Test Coverage

- Maintain explicit run manifest + trace output for diagnosability.
- Add/update tests for:
  - parser excluding non-event taxonomy objects,
  - preflight injection coverage behavior,
  - 429 wait/retry path behavior.

## Error Handling

- Keep strict explicit failures for malformed events, missing ground truth, and invalid injection payloads.
- Do not silently default, skip, or coerce run-critical failures.
- Limit the new permissive behavior to transient rate-limit handling only.

## Compatibility

- Additive behavior changes only.
- Existing CLI interface and output artifacts remain unchanged in shape.
- Existing scoring and evaluator contracts remain unchanged.

