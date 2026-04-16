# Offline Ollama Migration Design (MiroFish-Offline)

**Date:** 2026-04-16  
**Status:** Approved for planning  
**Branch target:** `phase0-minimal-strict-neo4j`

## 1. Problem Statement

Phase-0 benchmark runs currently depend on OpenRouter free-tier models and frequently fail under sustained 429 limits. This blocks end-to-end completion and prevents stable generation of:

- `run_manifest.json`
- `event_results.json`
- `summary.json`

For predictability benchmarking, we need a fully local/offline-capable execution path that preserves current architecture and telemetry contracts.

## 2. Goals and Non-Goals

### Goals

1. Make local Ollama the default inference path (offline-first).
2. Keep dual-mode capability (local + cloud) with explicit mode selection.
3. Preserve existing benchmark/orchestrator/simulation architecture.
4. Add strong model identity tracking/verification for reproducibility.
5. Keep manifest schema compatibility and deterministic benchmark behavior.
6. Improve resilience with provider-aware retry/backoff policy.

### Non-Goals

1. No refactor of core simulation logic, agent behavior flow, or orchestrator lifecycle.
2. No changes to benchmark scoring methodology itself.
3. No replacement of OpenAI SDK usage with Ollama CLI wrappers in app runtime.

## 3. Architecture Overview

Design follows a provider-abstraction approach with minimal surface changes:

- Keep existing entrypoints and role-based routing.
- Introduce a provider boundary behind existing config/router/client layers.
- Route role inference through `BenchmarkRoleRouter` with provider-mode awareness.

### Target integration points (existing files)

1. `backend/app/config.py`
2. `backend/app/benchmarks/role_router.py`
3. `backend/app/utils/llm_client.py`

No simulation/orchestrator core flow is changed.

## 4. Configuration Contract (Local-First + Backward Compatible)

## 4.1 Provider Mode

- `LLM_PROVIDER_MODE=local|cloud|auto`  
  - Default: `local`
  - `auto`: local preferred, cloud fallback only when cloud credentials and cloud role models are fully configured.

## 4.2 Base Runtime

- `LLM_BASE_URL=http://172.20.10.3:11434/v1`
- `LLM_API_KEY=ollama` (dummy but required by SDK)

## 4.3 Role Model Mapping

- `ROLE_MODEL_GRAPH=qwen2.5:7b`
- `ROLE_MODEL_BENCHMARK=qwen2.5:14b`
- `ROLE_MODEL_EVALUATOR=qwen2.5:14b`

Legacy `OPENROUTER_*` values remain supported in cloud/auto mode for backward compatibility.

## 4.4 Local Model Identity and Verification

For reproducibility and auditability:

- `model_name`: always required identity key (from config).
- `model_digest` or `model_version`: required when `BENCHMARK_MODE=true`.
- `VERIFY_LOCAL_MODEL=true|false`:
  - default: `true`
  - if true, validate configured model against provider metadata endpoint:
    - Ollama: `/api/tags`
    - OpenAI-compatible provider: `/v1/models`
- `ALLOW_UNVERIFIED_LOCAL=false` (default):
  - benchmark mode + unverifiable identity => fail-fast unless explicitly overridden.

### Manifest/telemetry identity fields

Manifest/logging records:

- `model_name`
- `model_digest` (if available)
- `model_resolved` (bool)
- `verification_source` (`api_tags`, `v1_models`, `config_only`, etc.)

## 5. LLM Provider and Routing Behavior

## 5.1 Router responsibilities

`BenchmarkRoleRouter` resolves:

1. provider mode (`local/cloud/auto`)
2. role-to-model mapping (`graph/benchmark/evaluator`)
3. verification policy and identity metadata

No hardcoded OpenRouter model IDs remain in routing behavior.

## 5.2 Client responsibilities

`LLMClient` remains OpenAI SDK based with `base_url` override and provider-aware options:

- timeout default raised to `120s` for local inference latency
- retry policy tuned for local queue congestion
- deterministic param propagation where applicable

## 6. Retry, Determinism, and Strictness

## 6.1 Retry Policy

Use exponential backoff with jitter:

- `LLM_RETRY_MAX_RETRIES`
- `LLM_RETRY_INITIAL_DELAY`
- `LLM_RETRY_MAX_DELAY`
- `LLM_RETRY_JITTER_MAX`

Local policy targets transient queue/busy/connectivity issues, not cloud-only assumptions.

## 6.2 Determinism Policy

- `BENCHMARK_MODE=true`: existing benchmark deterministic enforcement remains highest priority.
- `BENCHMARK_MODE=false` + `DETERMINISTIC_MODE=true`:
  - use `RANDOM_SEED`
  - stable request params for local dev reproducibility.

## 6.3 Telemetry and Failure Behavior

- `TELEMETRY_REQUIRED=true` remains strict (no mock fallback).
- Neo4j unavailable or insufficient telemetry coverage should fail clearly.
- Phase-0 minimal checkpoints remain `[6,12,18,24,30]`.

## 7. Deliverables and File Changes

## 7.1 `.env.example` updates

Add/organize:

- `LLM_PROVIDER_MODE`
- `ROLE_MODEL_GRAPH`, `ROLE_MODEL_BENCHMARK`, `ROLE_MODEL_EVALUATOR`
- `VERIFY_LOCAL_MODEL`
- `ALLOW_UNVERIFIED_LOCAL`
- `DETERMINISTIC_MODE`
- `RANDOM_SEED`
- timeout/retry knobs with local-friendly defaults

## 7.2 Refactor snippets (in existing modules)

- `backend/app/config.py`: load and validate new env contract.
- `backend/app/benchmarks/role_router.py`: dynamic provider+role resolution.
- `backend/app/utils/llm_client.py`: provider-aware timeout/retry/deterministic options.

## 7.3 Provisioning

Provide:

- `setup_ollama.sh`
- equivalent PowerShell commands in migration guide

Required pulls include at least:

- `qwen2.5:14b`
- `qwen2.5:7b`
- `nomic-embed-text`

## 7.4 Migration Guide

Add `MIGRATION_GUIDE.md` with:

1. local-only startup
2. cloud fallback mode
3. strict benchmark mode requirements
4. reproducibility/model-identity checklist
5. troubleshooting for model verification and queue congestion

## 8. Validation Plan

Post-refactor acceptance:

1. Local Ollama + Neo4j connectivity succeeds without internet dependency.
2. Phase-0 minimal run completes end-to-end in local mode.
3. Artifacts generated:
   - `run_manifest.json`
   - `event_results.json`
   - `summary.json`
4. Telemetry checkpoints `[6,12,18,24,30]` appear with valid `round_jsd`.
5. Manifest includes local model identity and verification metadata.

## 9. Risks and Mitigations

1. **Local queue saturation / long latency**  
   Mitigation: provider-aware backoff+jitter and increased timeout.

2. **Model identity ambiguity in local providers**  
   Mitigation: required configured `model_name`, API verification enabled by default, strict benchmark gating via digest/version.

3. **Backward compatibility regressions**  
   Mitigation: preserve cloud mode and legacy `OPENROUTER_*` compatibility path.

## 10. Rollout Strategy

1. Implement config + router + client refactor behind mode controls.
2. Verify local mode first (`LLM_PROVIDER_MODE=local`).
3. Validate strict benchmark behavior with deterministic contract.
4. Retain cloud path for contingency, but default to local in `.env.example`.

---

This design intentionally limits changes to configuration, provider routing, and client resilience boundaries while preserving existing benchmark architecture and manifest schema compatibility.
