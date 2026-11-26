# Phase 1: Core and Tenancy (backfilled summary)

Summary only. Authoritative sources: [modules.md](../../modules.md), the module specs, [traceability.md](../../traceability.md), [decisions.md](../../decisions.md).

## Status

**Phase 1 is owner-declared closed (SDD-D-1).** That is a delivery-status decision and does not assert that every acceptance criterion was independently verified. No Phase 1 requirement is `Verified`.

## Modules

| Module | Spec | Rows in traceability (as of 2026-11-20) |
| --- | --- | --- |
| auth | [auth-onboarding](../../specs/auth-onboarding/spec.md) | 15 Implemented, 1 Gap |
| workspace | [workspace](../../specs/workspace/spec.md) | 10 Implemented, 2 Gap, 1 Blocked (WS-AC-3) |
| profile | [profile](../../specs/profile/spec.md) | 14 Implemented, 1 Gap |

## Open work

- T-001: WS-AC-3 needs a real Neon TEST-branch concurrency run (SDD-D-2). Blocked until the owner authorizes it; planned as the first nightly CI Neon run, after T-002.
- T-003: retrospective requirement-level verification.
- T-009: approval metadata for the nine non-AI-Platform specs. T-010: frontend scope questions.
- T-016: the auth and workspace import cycle (conformance finding B-1), without changing AUTH-AC-2 or AUTH-AC-7.
- Tenant-isolation and role-matrix tests live in `tests/db` and run only in the database suite; T-013 makes that automatic.
