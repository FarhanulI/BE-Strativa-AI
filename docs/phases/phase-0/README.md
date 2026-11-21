# Phase 0: Foundation (backfilled summary)

Summary only. The authoritative sources are [modules.md](../../modules.md), the module specs and [traceability.md](../../traceability.md). Nothing here is a new requirement or decision.

## Modules

| Module | Spec | Rows in traceability (as of 2026-11-20) |
| --- | --- | --- |
| core | [spec](../../specs/core/spec.md) | 17 Implemented, 5 Gap |
| events_outbox | [spec](../../specs/events-outbox/spec.md) | 4 Implemented, 3 Gap |
| jobs_workers | [spec](../../specs/jobs-workers/spec.md) | 6 Implemented, 1 Gap |
| observability_audit | [spec](../../specs/observability-audit/spec.md) | 5 Implemented, 1 Gap |
| db_migrations | [spec](../../specs/db-migrations/spec.md) | 8 Implemented |
| api_contract | [spec](../../specs/api-contract/spec.md) | 5 Implemented, 1 Gap |
| web_foundation | none (T-007) | no rows |

No Phase 0 requirement is `Verified`.

## Delivery record

- The [Phase 0 verification report](../../reports/phase0-verification.md), dated 2026-10-14, records a close-out on the dedicated Neon test branch only, with a real Redis demo. It is **historical evidence for that date**. It does not verify current behavior: the database guard, local test mode and migrations 0005 to 0008 came afterwards (traceability rule 9).
- Documented deviations are listed in [decisions.md](../../decisions.md) section 4.

## Open work

- T-002: re-verify Phase 0 at requirement level against the current code.
- T-007: `web_foundation` has no spec; the frontend task must provide it.
- T-015: real-Redis tests for JOB-AC-2, OUT-AC-3 and OBS-AC-3, which are `Gap` today.
- T-021: generated data model and drift gate.
- Findings E-1 to E-4 in the [conformance report](../../architecture/conformance-report.md).
