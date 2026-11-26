# T-008: Remaining AI Platform implementation and verification gaps

- **Module and phase:** ai_platform, Phase 2
- **State:** Ready
- **Requirement IDs:** status re-read from [traceability.md](../traceability.md) on 2026-11-25 (after T-011, T-022, T-023, T-024).
  - `Specified` (no implementation identified): INV-1, INV-16, INV-25, INV-27, INV-28; AC-1, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-47, AC-48, AC-49, AC-50, AC-54, AC-55, AC-56, AC-57.
  - `Implemented`, partial (named in the matrix as incomplete): AC-45 (reaper clause), AC-46 (no `reconcile_budgets` handler, audit record or log), AC-58 (one settle-versus-abandon race only), AC-60 (`task_min_input_units` and `latency_p50_ms` values unverified), AC-61 (adapter part waits for the adapter), AC-53 (wire-format clause waits for the adapter path).
  - Every other AI Platform requirement that is `Implemented` and not `Verified` is verified under sub-task T-008-F.
  - **Removed from the original list because the matrix no longer shows them as open:** INV-4, INV-26, AC-9, AC-51, AC-60 (now `Implemented`, kept above only where partial), AC-15 (`Verified` by T-011), AC-38 (a test is now mapped; `Implemented`, verification under T-008-F).
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md), sections 16, 17.1 to 17.7, 20 (decisions D-2, D-5, D-11, D-14, D-16, D-20, D-24, D-27, D-31, D-36); [traceability.md](../traceability.md)
- **Dependencies:**
  - T-004 (D-32 owner resolution, Blocked) and T-005 (D-20 revision metadata, Blocked) for governance only; neither blocks the sub-tasks below.
  - T-006 is Accepted; the `decisions.md` section 6 row on revisions 5 to 7 is still stale and needs an owner-approved docs update (sub-task T-008-A).
  - T-011, T-022, T-023, T-024, T-017, T-018, T-019, T-015 are Accepted and are inputs, not blockers.
  - SDD-D-3: feature development resumes only after the owner approves the SDD foundation.
  - Real-provider work (T-008-E) needs the separately authorized provider setup in spec section 17.6 (spend cap 20 USD total, INV-27, D-11, D-16) and the owner's privacy review (D-27).

## Objective
Keep the AI Platform work that is not yet implemented or not yet verified visible, and break it into bounded, owner-approvable sub-tasks so each runs under the SDD workflow. This task is the umbrella and the index of those sub-tasks. It changes no code.

## Scope
Proposed split. Each sub-task becomes its own `T-nnn` file through `sdd-prepare-task` and needs its own owner approval as `Ready`. The order shows dependencies, not a commitment.

| Sub-task | Content | Requirement IDs | Depends on | Review tier (sdd.md section 9) |
| --- | --- | --- | --- | --- |
| T-008-A Governance | Owner-approved docs update of the stale `decisions.md` section 6 revision 5 to 7 row; keep T-004 and T-005 tracked. | None new (governance) | T-004, T-005 owner input | Docs only, milestone review |
| T-008-B LiteLLM adapter | `app/ai_platform/adapters/` package behind the Router; the only importer of `litellm`; output cap passed as the provider limit; embedding wire format. | INV-1, AC-1; AC-61 adapter part; AC-53 wire-format clause; D-20 deadlines | T-017, T-018 (Accepted) | Strict: AI target and dependency use; `ai-reviewer` and `architect-reviewer` before result review |
| T-008-C Async path | `submit`, `handle_once` consumer, `execute_request` handler, lease claim, heartbeat, fenced statements, missing-credentials ending, job redelivery no-op. | INV-16, INV-28; AC-39, AC-40, AC-41, AC-42, AC-43, AC-44; AC-45 reaper clause; AC-58 full | T-008-B (real provider path not required; fake provider suffices), T-015 | Strict: events, jobs, authorization |
| T-008-D Periodic jobs and purge | `reap_stale_requests`, `reconcile_budgets` (audit record and log), `purge_expired_content`, `python -m app.ai_platform.cron`. | INV-25; AC-46 rest, AC-47, AC-48, AC-49, AC-50 | T-008-C (reaper and lease) | Strict: retention and privacy behavior |
| T-008-E Real-provider smoke | `ai_live` suite, git-ignored local ledger, per-session and cumulative spend guards, one embed and one Gemini call, synthetic text only. | INV-27; AC-54, AC-55, AC-56, AC-57 | T-008-B; owner authorization of keys and paid calls; D-27 | Strict: paid calls, secrets |
| T-008-F Verification of Implemented rows | Map missing tests and execute them for every `Implemented` AI Platform row, including AC-38; record dated evidence. | all other `Implemented` IDs; AC-60 values and AC-61 Router part confirmed | None for DB-free; `/run-db-suite` for DB rows | Milestone review, `spec-auditor` per task |

## Non-goals
Implementing anything under this task as written; it is a tracking task. New AI features outside the spec. Real-provider calls without the spec's spend controls and the owner's explicit authorization. Neon runs (a separate authorized task). Editing the approved spec; a conflict needs a change proposal. Redefining or renumbering D-32 (T-004).

## Implementation expectations
Each sub-task is prepared with `sdd-prepare-task`, owner-approved as `Ready`, and cites its requirement IDs and the applicable decisions (D-n). Sub-tasks follow the tier of section 9: those in the table marked Strict stop for result review before the next starts. Events and logs carry ids only, no `token` key, no prompts or completions. Every task states its expected evidence before work starts. Any new environment variable follows the ENV RULE (`.env.example` plus `scripts/sync_env_local.py`).

## Required tests
Those named in the spec for each AC (sections 17.1 to 17.6). Unit tests are DB-free. Database tests run only through `/run-db-suite`. Real-provider tests use the `ai_live` marker, are excluded from `scripts/check.py` and `just test-db`, and run only with `AI_LIVE_TESTS=1`.

## Verification requirements
Dated execution evidence per ID, recorded as a verification report linked from the traceability Evidence cell (exact command, exit code, counts, environment, date; `NOT RUN` with the reason otherwise). Environment: local Postgres (`TEST_DB_MODE=local`, `APP_ENV=test`). Local Postgres never verifies a requirement that names Neon. Real-provider tests only under the 20 USD total cap, the 2 USD per-session guard and synthetic text. A fresh-context `spec-auditor` reports PASS, PARTIAL or FAIL per criterion before each sub-task moves to `Verified` or owner review.

## Acceptance criteria
- The sub-task list above is approved by the owner (or amended), and each sub-task has its own task file.
- Every listed ID is `Verified` with dated matching evidence, or stays `Specified`, `Implemented`, `Gap` or `Blocked` with the reason recorded in traceability.
- T-008 is closed only when every sub-task is Accepted, or deferred with the reason recorded.

## Evidence
None recorded.

## Review and approval
Approved by the owner as `Ready` on 2026-11-25, with the sub-task split A to F as proposed. This approval covers the umbrella and the split only. Each sub-task still needs its own `sdd-prepare-task` file and owner approval before work starts. Start order and the deferral of T-008-E are not yet decided by the owner (recommended: T-008-F for DB-free rows, then T-008-B; T-008-E deferred until provider keys and the D-27 privacy review exist).

Proposed commit message:

```
docs(T-008): re-baseline AI Platform remaining gaps and propose sub-task split

Refresh the T-008 requirement list against traceability after T-011, T-022,
T-023 and T-024 (INV-4, INV-26, AC-9, AC-15, AC-38, AC-51 no longer open).
Split the remaining INV-1, INV-16, INV-25, INV-27, INV-28 and AC-1, AC-39 to
AC-44, AC-47 to AC-50, AC-54 to AC-57 work into sub-tasks A to F. Docs only.
State stays Proposed.


```
