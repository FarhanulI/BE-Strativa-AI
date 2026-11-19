# Decision Register

This is the central index and cross-module decision record. It is **not** a replacement for the module specifications.

- The original module specifications remain the authoritative source for their detailed decisions. Nothing here moves, rewrites, renumbers or replaces them.
- Where this register summarises an existing decision, the label is a non-normative pointer. The spec text governs.
- Existing historical decisions and new SDD migration decisions use separate ID namespaces (section 1).

## 1. ID namespaces

| Namespace | Meaning | Defined in |
| --- | --- | --- |
| `D-n` | Historical AI Platform decisions D-1 to D-35 (D-32 is not defined; section 6) | [AI Platform spec, section 20.1](specs/ai-platform/spec.md) (authoritative text) |
| `OQ-n` | Historical AI Platform open questions | [AI Platform spec, section 19](specs/ai-platform/spec.md) |
| `SDD-D-n` | New decisions made for the Spec-Driven Development (SDD) migration | This document, section 2 |
| `<MODULE>-INV-n`, `<MODULE>-AC-n` | Requirement IDs of the nine non-AI-Platform specs (SDD-D-5). Requirements, not decisions. | The module spec |
| `T-nnn` | Task IDs (SDD-D-6). Tasks, not requirements or decisions. | [docs/tasks/](tasks/README.md) |

`D-n` identifiers are never redefined here. New decisions always take an `SDD-D-n` ID, or a module-specific namespace that is introduced by that module's own spec.

## 2. SDD migration decisions (new)

SDD-D-1 to SDD-D-4 were made by the owner on **2026-11-19** and are recorded as supplied for the SDD migration. SDD-D-5 and SDD-D-6 are the accepted migration decisions of the finalization milestone, recorded the same day. SDD-D-7 resumes product development.

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

### SDD-D-5: Module-prefixed requirement identifiers

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision, finalization milestone)
- **Decision:** Requirements in the nine non-AI-Platform specs use `<MODULE>-INV-<n>` and `<MODULE>-AC-<n>` with the codes CORE, OUT, JOB, OBS, DBM, API, AUTH, WS and PROF. Existing AI Platform `INV-n`, `AC-n`, `D-n` and `OQ-n` identifiers are preserved exactly and are not prefixed. SDD governance decisions stay `SDD-D-n`.
- **Rationale:** Unprefixed numbers collide across modules. Renumbering the AI Platform would break references in its spec, code and tests.
- **Consequences:**
  - IDs are stable and are never reused or renumbered. Only normative, verifiable statements receive IDs; one top-level bullet of a spec's Invariants or Acceptance criteria section is one requirement, so inseparable checks are not split.
  - Frontend design material (for example Auth cookie/BFF and Profile concurrency screens) is not converted into IDs until its normative scope is established (section 6).
  - Assignment was applied in order of appearance in each spec at the time of the migration. The requirement text was not changed.

### SDD-D-6: Task workflow

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision, finalization milestone)
- **Decision:** Work is organised as `T-nnn` task files in [docs/tasks/](tasks/README.md) with the lifecycle Proposed, Ready, In Progress, Implemented, Verified, Accepted, plus Blocked. The process is defined in [sdd.md](sdd.md).
- **Rationale:** Requirements, tasks and evidence need separate identifiers so that a task can close without changing a requirement's verification status.
- **Consequences:**
  - Substantial implementation requires a `Ready` task that names requirement IDs, scope, non-goals, required tests and verification.
  - Task IDs are never used as requirement IDs.
  - Blocked work stays visible and is not marked complete.

### SDD-D-7: Product development resumes under SDD

- **Date:** 2026-11-19
- **Status:** Accepted (owner decision)
- **Decision:** The owner accepts the completed SDD governance foundation and authorizes resumption of product development under the SDD workflow ([sdd.md](sdd.md)). This supersedes the development pause in SDD-D-3. SDD-D-3 is historical and is not modified.
- **Rationale:** The SDD foundation (decisions, traceability matrix, task workflow) is complete and accepted, so the migration pause no longer applies.
- **Consequences:**
  - Feature work may proceed only through an owner-approved `Ready` task that names requirement IDs (sdd.md; rules 11 to 17).
  - Phase 1 remains owner-declared closed, not technically verified (SDD-D-1).
  - Workspace Neon concurrency verification stays mandatory and needs separate explicit authorization (SDD-D-2). This decision authorizes no Neon operation.
  - Existing architecture, module boundaries, phase sequencing and security rules remain authoritative.
  - Existing verification gaps stay visible. No requirement is `Verified` without dated execution evidence.

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
| D-20 | Quality, latency and cost classes of `EMBED_TEXT` | new (revision not stated; unresolved, section 6) |
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
| Workspace Neon TEST-branch concurrency criterion (WS-AC-3) | [Workspace spec, Acceptance criteria](specs/workspace/spec.md) | Required and not yet evidenced; see SDD-D-2. Blocked on separate owner authorization; task T-001 |

## 6. Unresolved historical discrepancies and owner questions

Recorded as found. None is resolved here, none is guessed, and no code, test or spec reference was changed to hide it.

| Item | Finding | Owner resolution task |
| --- | --- | --- |
| D-32 reference discrepancy | The AI Platform decision table goes from D-31 to D-33. D-32 is cited in code and tests (`app/ai_platform/failure_policy.py`, `tests/unit/ai_platform/test_failure_policy.py`) but never appears in the spec's decision register or in the history inspected in the Milestone 2 assessment. No D-32 decision is created, its meaning is not inferred, and D-33 onward are not renumbered. The existing references are preserved. | T-004 |
| D-20 revision metadata | D-20 is present and its text is preserved. The spec's revision summary states no revision for it, so no revision number is assigned. | T-005 |
| AI Platform approval history | The spec contains revision 7 content but its Status refers to owner approval of revision 4. Revision 4: approval recorded. Revisions 5 to 7: changes present, approval not established by available evidence. The spec header now states this without rewriting history. | T-006 |
| Approval metadata of the other nine specs | Specification status, revision, approval status and approval date are `Not stated` or `Not recorded` in each spec. No value was invented. | T-009 |
| Frontend normative scope | Onboarding stays frontend-derived state, not a backend module. The Auth cookie, BFF and wizard material and the Profile frontend concurrency material were not converted into acceptance criteria. Whether any of it is normative for the backend, or belongs to a frontend spec, is undecided. Note: the backend Profile invariant PROF-INV-4 on `If-Match` already covers the backend side. | T-010 |
| web_foundation spec | `docs/specs/web-foundation/spec.md`, expected by the module map, is not in this repository. No substitute was written. It stays outside backend traceability until the frontend scope provides it. `../web` was not inspected. | T-007 |
| Stray line in the Auth spec | Line 1 of `docs/specs/auth-onboarding/spec.md` is an orphan table row for `PATCH /me` above the title. It was left unchanged. | T-010 |
| OQ numbering | A revision note's "was OQ-n" can name a different question than the current OQ-n. Use AI Platform section 19 for current open questions. | none |

## 7. Edits to specifications during the migration

SDD-D-3 paused spec edits unless a milestone authorized them. The finalization milestone authorized, and was limited to: adding requirement IDs and a metadata block to the nine non-AI-Platform specs, and adding a metadata block to the AI Platform spec. No requirement text, decision or existing identifier was changed.
