# T-019: `instructions_version` on AI requests (change proposal, then nullable migration)

- **Module and phase:** ai_platform, Phase 2
- **State:** Accepted (stops 1 and 2 done 2026-11-21; DB-free gate and local DB suite green; accepted by the owner 2026-11-21)
- **Requirement IDs:** None for the proposal (it is a spec change proposal under [sdd.md](../sdd.md) section 7). If approved it adds new requirements with the next free `AC-n`; no existing ID is renumbered. Existing requirements that touch the changed text are listed by `sdd-analyze-spec` when the task is prepared.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) 4.1 (`ai_requests`), 5.1 (request types), 12.4 (logging and privacy), D-6 (domain modules own and version prompts); [conformance report](../architecture/conformance-report.md) F-2
- **Dependencies:** Owner approval of the proposal. **Must be settled (decision recorded and the nullable migration verified) before T-011 starts**, because T-011 forbids schema changes and the orchestrator would otherwise be revisited. T-020 follows this task.

## Objective
Let a caller state which version of its instructions produced a request, and store it, so that quality, latency and cost can be attributed to a prompt change.

## Proposed spec text (for owner review; not applied)
- **4.1, new column:** `instructions_version` text, null. An opaque, caller-supplied label for the trusted instructions text (D-6). Not content: a label only. Existing and embedding rows are null.
- **5.1:** `AiTaskRequest` gains `instructions_version: str | None = None` (the task text said `AiRequest`, which is the ORM model; it gets the column). The platform never interprets it, never derives it from content, and never uses it to route.
- **Constraints (to confirm, SDD-Q-4):** non-blank when present; at most 64 characters; characters limited to letters, digits and `._:-`; rejected, not truncated, otherwise.
- **12.4:** the value may appear in logs and audit details; it is not placed in events until a consumer needs it.
- **Nullable first:** no backfill, no `NOT NULL`. Making it required for non-embedding tasks is a later change once a domain module calls the platform.

## Scope
**Part A, proposal.** Finalize the text above with the owner and record the decision (an `SDD-D-n` or a spec decision, as the owner chooses). No code.
**Part B, implementation (after approval).** Migration `0009` adding the nullable column (additive, reversible, no data change), the model field, the request repository and request types, and tests. `alembic check` stays clean.

## Non-goals
Prompt text storage or hashing of content. Required-ness. Usage-record column (the request row is reachable from usage rows by `request_id`). Metric views (T-020). The orchestrator (T-011).

## Implementation expectations
Part B only after Part A is approved. Boundaries: the column belongs to `ai_requests`, owned by `ai_platform`. Constraint violations raise the existing validation error type. No label appears in an error beyond the field name.

## Required tests
Validation (blank, too long, bad characters, null), persistence round trip, migration upgrade/downgrade/upgrade and drift check through `/run-db-suite`, and the existing schema reflection tests updated.

## Verification requirements
Dated runs with commands, exit codes and counts (T-014 format). Local PostgreSQL only; no Neon.

## Acceptance criteria
The owner has recorded the decision; the migration is additive and reversible; round trip and constraint tests pass with evidence; no existing requirement changes status.

## Evidence
- 2026-11-21 stop 1: prepare step read spec 4.1, 5.1, 12.4 and the code (`AiTaskRequest` in `requests.py`, `AiRequest` ORM in `models.py`, next migration `0009` after `0008_ai_platform`). Owner confirmed: label is part of the canonical request (a different label under one key is a `Conflict`), SDD-Q-4 constraints, a database CHECK, decision `D-36`. Change proposal written: [CP-2](../specs/ai-platform/change-proposals/CP-2-instructions-version.md). No code or spec edit has happened.

## Review and approval
Not requested. **Gate: always** (migration; contract; AI target).
- 2026-11-21 stop 2: CP-2 approved and applied as spec revision 9 (D-36, AC-62, AC-63). Migration `0009_instructions_version`, model column and CHECK, `AiTaskRequest.instructions_version`, repository parameter, tests. Record with commands, counts and deviations: [stop 2 record](../reports/2026-11-21-T-019-instructions-version.md) (check.py 1762 passed, 4 skipped). The DB tests (17 new, deselected) have not run; AC-62 and AC-63 are `Implemented`, not `Verified`.
- 2026-11-21 local DB suite, run by the owner with `/run-db-suite all`: exit 0, 217 passed (200 earlier plus 17 new), 0 failed, 1766 deselected, skipped not reported by the script, `cleanup done`. Local Postgres, not Neon. AC-63 `Verified`; AC-62 stays `Implemented` because the same-key different-label `Conflict` clause needs `submit` (T-011). Recorded in the [T-019 record](../reports/2026-11-21-T-019-instructions-version.md).
- 2026-11-21 owner accepted T-019. T-011 may now start (its precondition, a settled `instructions_version`, is met).
