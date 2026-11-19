# Decision Register

This is the central index and cross-module decision record. It is **not** a replacement for the module specifications.

- The original module specifications remain the authoritative source for their detailed decisions. Nothing here moves, rewrites, renumbers or replaces them.
- Where this register summarises an existing decision, the label is a non-normative pointer. The spec text governs.
- Existing historical decisions and new SDD migration decisions use separate ID namespaces (section 1).

## 1. ID namespaces

| Namespace | Meaning | Defined in |
| --- | --- | --- |
| `D-n` | Historical AI Platform decisions D-1 to D-35 | [AI Platform spec, section 20.1](specs/ai-platform/spec.md) (authoritative text) |
| `OQ-n` | Historical AI Platform open questions | [AI Platform spec, section 19](specs/ai-platform/spec.md) |
| `SDD-D-n` | New decisions made for the Spec-Driven Development (SDD) migration | This document, section 2 |

`D-n` identifiers are never redefined here. New decisions always take an `SDD-D-n` ID, or a module-specific namespace that is introduced by that module's own spec.

## 2. SDD migration decisions (new)

All four decisions were made by the owner on **2026-11-19** and are recorded as supplied for the SDD migration.

### SDD-D-1: Phase 1 is owner-declared closed

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision)
- **Decision:** Phase 1 (Core & Tenancy: auth, workspace, profile) is closed as a delivery phase and is not reopened as one.
- **Statement:** Phase 1 is owner-declared closed. This is a delivery-status decision and does not assert that every Phase 1 acceptance criterion has been independently verified.
- **Rationale:** The owner closed the delivery phase so that work could move to the SDD migration. Closing a phase is a scheduling and ownership decision, separate from the evidence for each requirement.
- **Consequences:**
  - Phase 1 is not reopened for feature delivery.
  - No Phase 1 requirement is marked `Verified` without dated test evidence (see [traceability.md](traceability.md)).
  - Requirement-level verification for Phase 1 stays subject to retrospective traceability and to the Neon verification in SDD-D-2.

### SDD-D-2: Neon concurrency verification remains mandatory

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision)
- **Decision:** The Workspace specification's real Neon TEST-branch concurrency criterion stays mandatory: "A real Neon TEST-branch concurrency test proves concurrent demotion/removal cannot leave a workspace without an OWNER" ([Workspace spec, Acceptance criteria](specs/workspace/spec.md)).
- **Statement:** The Workspace concurrency requirement remains mandatory and requires a separately authorized Neon TEST-branch verification task.
- **Rationale:** Local PostgreSQL is not an equivalent substitute for the real Neon TEST branch that the spec names.
- **Consequences:**
  - The criterion is not satisfied by a local PostgreSQL run and must not be recorded as `Verified` on that basis.
  - Neon verification is a separate, explicitly authorized task. The SDD migration milestones do not authorize a Neon connection or execution.
  - The existing environment guard and the rule that tests never target dev or production remain in force.
  - Until that task runs and produces dated evidence, the criterion stays open in the traceability matrix.

### SDD-D-3: Feature development is paused during the SDD migration

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision)
- **Decision:** No new product features and no AI Platform feature work are implemented during the SDD migration. Work is limited to the approved SDD migration milestones.
- **Rationale:** The migration needs a stable baseline, and feature changes during it would move the target.
- **Consequences:**
  - Feature development resumes only after the owner approves the completed SDD foundation.
  - Module specifications are not edited as part of the migration milestones unless the owner approves a specific milestone that says so.

### SDD-D-4: Approval granularity is milestone-based

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision)
- **Decision:** Owner approval is requested per milestone, not per small action.
- **Rationale:** Routine work inside an approved milestone does not need approval after every action, while each milestone is still reviewed as a whole.
- **Consequences:**
  - Routine tasks inside an approved milestone may proceed without asking after each small action.
  - Work stops for owner review at the end of each milestone, and the next milestone does not start without owner approval.
  - The existing requirement to commit and push after each logical change is unchanged (see Standing rules in [.github/copilot-instructions.md](../.github/copilot-instructions.md)).

## 3. Index of existing AI Platform decisions (D-1 to D-35)

Source: [AI Platform spec, section 20.1](specs/ai-platform/spec.md). The spec states that D-1 came from the review, D-2 to D-13 were first-draft Open Questions, revision 2 changed D-2, D-4, D-5, D-9 and D-11 and added D-14 and D-15, revision 3 changed D-4 and added D-16 to D-19, revision 4 changed D-4 and D-16 and added D-21 to D-23, revision 5 added D-24 to D-29, revision 6 added D-30 and D-31, and revision 7 added D-33 to D-35. D-20 is marked "new" with no revision stated in the spec's summary.

The "Topic" column is a short index label only and is not normative.

| ID | Topic (non-normative) | Revision note in spec |
| --- | --- | --- |
| D-1 | Separate system budget for system-scope calls | new (review) |
| D-2 | No generic scheduler; external cron CLI | was OQ-1; rev 2 |
| D-3 | Budget period is the UTC calendar month | was OQ-2 |
| D-4 | Chat provider policy and billing-mode rules | was OQ-3; rev 2; changed rev 4 |
| D-5 | 30-day retention of stored async content | was OQ-4; rev 2 |
| D-6 | Prompt ownership; `ai:usage_read` role access | was OQ-5 |
| D-7 | `run()` from request path only for interactive tasks | was OQ-6 |
| D-8 | No budget exemptions at 100 % | was OQ-7 |
| D-9 | Budget limits from config only | was OQ-8; rev 2 |
| D-10 | Local-database mode for test guard (prerequisite P-2) | was OQ-9 |
| D-11 | Enforcement of the real-provider spend cap | was OQ-10; rev 2 |
| D-12 | No streaming in this phase | was OQ-11 |
| D-13 | Missing provider key behavior | was OQ-12 |
| D-14 | Advisory budget pre-check at submit | was OQ-2 of rev 1 |
| D-15 | System scope only for `EMBED_TEXT` | was OQ-3 of rev 1 |
| D-16 | Real embedding smoke-test key and spend limit | was OQ-2 rev 2; changed rev 4 |
| D-17 | `ON DELETE CASCADE` on `ai_*` foreign keys for now | was OQ-3 rev 2 |
| D-18 | Notification flags and budget `state` computation | was OQ-4 rev 2 |
| D-19 | Billing mode belongs to the provider credential | new, rev 3 |
| D-20 | Quality, latency and cost classes of `EMBED_TEXT` | new (revision not stated) |
| D-21 | Perplexity embedding model replaces the earlier choice | new, rev 4 |
| D-22 | Perplexity key variable and explicit key passing | was OQ-3 rev 4 |
| D-23 | Total embedding request limit; splitting belongs to `rag` | was OQ-4 rev 4 |
| D-24 | Reservation amount equals the Router estimate | new, rev 5 |
| D-25 | Router does not rank by JSON-schema support | new, rev 5 |
| D-26 | Effective `max_output_units` resolution | new, rev 5 |
| D-27 | Privacy gate: synthetic text only until review recorded | new, rev 5 |
| D-28 | Quality-class routing rules | new, rev 5 |
| D-29 | Embedding batching and retry owned by `rag` | new, rev 5 |
| D-30 | Router ranking kept for interactive latency class | was OQ-5 rev 6 |
| D-31 | Router exposes `effective_max_output_units` | was OQ-4 rev 6 |
| D-32 | **Not present in the spec's decision table** (see section 6) | none |
| D-33 | All budget refusals use one refusal transaction | new, rev 7 |
| D-34 | Reservation of a repair call | new, rev 7 |
| D-35 | Circuit-breaker denial at call time | new, rev 7 |

## 4. Phase 0 and other documented deviations and close-out decisions

These stay where they are written. They are listed here so they can be found from one place.

### Phase 0 close-out decisions

Source: [Phase 0 verification report, Close-out Decisions](reports/phase0-verification.md). The report numbers them 1 to 4 and they keep that numbering. Evidence in that report is dated 2026-10-14 and covers the dedicated Neon test branch only.

1. Branch/environment validation remains enforced when a database URL is configured, preserving DB-free OpenAPI generation.
2. The foundation modules were implemented and verified without adding Phase 1 features.
3. The close-out certifies only the dedicated test branch, not dev or production.
4. The local setup repair added only the missing `APP_ENV` and `NEON_BRANCH_NAME` selectors and did not weaken the environment guard.

The summaries above are paraphrases. The report text governs.

### Documented deviations

| Source | Deviation (non-normative summary) |
| --- | --- |
| [api_contract, Deviations](specs/api-contract/spec.md) | `create_app` takes separate `database_check` and `redis_check` callables instead of `readiness_dependencies`. |
| [db_migrations, Deviations](specs/db-migrations/spec.md) | `build_async_engine` does not retry the first connection; only the readiness checker retries. |
| [jobs_workers, Deviations](specs/jobs-workers/spec.md) | `JobQueue.enqueue(job)` does not validate against a job-schema registry at enqueue time. |
| [ai_platform, section 5.2](specs/ai-platform/spec.md) | Deliberate deviation from "caller owns the session" for transaction ownership. |
| [auth_onboarding, Frozen design notes](specs/auth-onboarding/spec.md) | Frontend design deviations (muted-text token, wizard content). Listed for completeness. |

## 5. Open items carried over unresolved

These are preserved as unresolved. This register does not decide them.

| Item | Where | State |
| --- | --- | --- |
| OQ-1 Distance metric and normalization for embeddings | [AI Platform spec, section 19](specs/ai-platform/spec.md) | Open (recommendation recorded in the spec; undecided) |
| OQ-2 Perplexity terms and privacy for submitted content | same | Open; D-27 gates real user data meanwhile |
| OQ-3 Reasoning units and the output cap | same | Open; to be decided in the catalog step |
| Operational prerequisites and unverified implementation inputs | [AI Platform spec, sections 20.3 and 20.4](specs/ai-platform/spec.md) | As written in the spec; the owner-selected model identifiers are marked unverified there |
| Workspace Neon TEST-branch concurrency criterion | [Workspace spec, Acceptance criteria](specs/workspace/spec.md) | Required and not yet evidenced; see SDD-D-2 |

## 6. Observations for owner review

- **D-32 is absent.** The AI Platform decision table goes from D-31 to D-33. The spec's revision summary says revision 7 records D-33 to D-35 and says no earlier numbering changed. This register does not assign, fill or explain D-32. The owner should confirm whether it is an intentional gap.
- The first draft of the AI Platform spec refers to "was OQ" numbers from earlier revisions, so "OQ-n" in a revision note can mean a different question than the current OQ-n. Use section 19 for current open questions.
