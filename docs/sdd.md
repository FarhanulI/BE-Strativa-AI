# Spec-Driven Development (SDD) Workflow

This is the single process document for how work is specified, tasked, implemented, verified and accepted in this repository. It defines process only. It does not restate requirements, decisions or architecture; it links to the documents that own them.

Agent rules that enforce this process are in [.github/copilot-instructions.md](../.github/copilot-instructions.md) (imported by `CLAUDE.md`). Decisions that created this process are SDD-D-1 to SDD-D-8 in [decisions.md](decisions.md).

## 1. Authority hierarchy

When two documents disagree, the higher one wins. Record the conflict (section 7); do not silently resolve it.

| Rank | Document | Authoritative for |
| --- | --- | --- |
| 1 | [product-architecture.md](product-architecture.md) | Product and architectural direction |
| 2 | [modules.md](modules.md) | Module ownership and phase sequencing (37 modules, 10 phases) |
| 3 | Module specifications, `docs/specs/<feature>/spec.md` | Normative requirements (invariants, acceptance criteria) |
| 4 | [decisions.md](decisions.md) and decision sections of specs | Accepted decisions and historical rationale |
| 5 | [traceability.md](traceability.md) | Link from each requirement to implementation, test, evidence and status |
| 6 | Tasks, [docs/tasks/](tasks/README.md) | Approved, bounded units of work |
| 7 | Verification records, `docs/reports/` | Dated execution evidence |

Safety, environment, database and repository rules in the Standing rules of [.github/copilot-instructions.md](../.github/copilot-instructions.md) apply to every rank and are never relaxed by a lower document.

## 2. Terms

| Term | Meaning | Where it lives |
| --- | --- | --- |
| Module | An architectural ownership boundary (entities, tables, services, routes, events, jobs, tests). 37 modules. | [modules.md](modules.md) |
| Phase | A delivery grouping and build order. 10 phases (0 to 9). A phase is not a module. | [modules.md](modules.md) |
| Requirement | One normative, verifiable statement in a spec: an invariant (`INV`) or acceptance criterion (`AC`). | Module spec |
| Decision | An accepted choice with rationale. `D-n` (AI Platform history), `SDD-D-n` (SDD governance). | [decisions.md](decisions.md), AI Platform spec 20.1 |
| Task | A bounded unit of work that references requirement IDs. IDs are `T-nnn`. | [docs/tasks/](tasks/README.md) |
| Milestone | An owner-reviewed stage of the SDD migration or of delivery. Owner approval is per milestone (SDD-D-4). | Task and report records |
| Verification evidence | A dated record of an actual execution (test run, demo, review) tied to a requirement. | [traceability.md](traceability.md), `docs/reports/` |

## 3. Requirement identifiers

- Format: `<MODULE>-INV-<n>` and `<MODULE>-AC-<n>`. Codes: CORE (core), OUT (events_outbox), JOB (jobs_workers), OBS (observability_audit), DBM (db_migrations), API (api_contract), AUTH (auth), WS (workspace), PROF (profile).
- The AI Platform keeps its original unprefixed `INV-n`, `AC-n`, `D-n`, `OQ-n` (SDD-D-5). Treat them as `AI`-module identifiers when a module name is needed; they are never renamed.
- IDs are stable. Never reuse, renumber or reassign an ID. A removed requirement keeps its ID, marked withdrawn in the spec.
- Only normative, verifiable statements get IDs. Purpose, non-goals, design notes and frontend design material do not.
- A new module gets a unique code when its spec is first approved. Add the code to this section.
- Add a new requirement by appending the next number in the owning spec. Changing an approved requirement follows section 7.

## 4. Workflow

`Specification -> Requirement IDs -> Traceability -> Task -> Implementation -> Tests -> Evidence -> Review -> Completion`

1. **Specification.** Read the module map entry and the module spec. Confirm the owning module and phase. Check [decisions.md](decisions.md) and the architecture sections the spec cites.
2. **Requirement IDs.** List the IDs the work satisfies or changes. If none apply, the spec needs a change first (section 7).
3. **Traceability.** Confirm each ID has a row in [traceability.md](traceability.md); add rows for new IDs with status `Specified`.
4. **Task.** Create or update a task file (section 5) and obtain its `Ready` state. Substantial implementation does not start without a `Ready` task. A one-line typo fix or doc link repair does not need a task.
5. **Implementation.** Work only inside the task scope. Keep module boundaries (public interfaces and domain events only). Commit and push after each logical step with a message that cites the task and requirement IDs.
6. **Tests.** Add or update tests for each applicable acceptance criterion. Tests that cross a module or tenant boundary need isolation coverage. The database suite runs only through `/run-db-suite`. Neon runs only in a separately authorized task.
7. **Evidence.** Execute the tests. Record the actual result with date, command or skill used, environment and counts in the task and in [traceability.md](traceability.md). Never record a result that was not produced.
8. **Review.** The owner reviews at milestone level (SDD-D-4), except for the task categories that section 9 reviews per task (SDD-D-8). An independent audit (section 11) precedes owner review.
9. **Completion.** A task is `Accepted` only after owner review. Update status of each requirement row from the recorded evidence.

## 5. Tasks

Task files live in [docs/tasks/](tasks/README.md) as `T-nnn-<slug>.md`. A task is a bounded plan, not a requirement. Task IDs are never used in place of requirement IDs.

Lifecycle:

`Proposed -> Ready -> In Progress -> Implemented -> Verified -> Accepted`, plus `Blocked`.

| State | Meaning | Entry condition |
| --- | --- | --- |
| Proposed | Described, not yet approved | Any author |
| Ready | Scope, requirement IDs, tests and verification approach are complete; dependencies named | Owner approval (per milestone, SDD-D-4) |
| In Progress | Work has started | Task is `Ready` |
| Implemented | Code and tests written; not yet executed to evidence | Implementation references recorded |
| Verified | Required tests executed with dated evidence in the task and traceability | Evidence recorded and reproducible |
| Accepted | Owner reviewed the evidence | Owner review |
| Blocked | A named dependency or authorization prevents progress | Blocker named in the task; state the previous state to return to |

A task is `Blocked` while waiting for owner authorization, an owner decision or a missing document. A `Blocked` task is never silently dropped or marked complete.

## 6. Requirement status

The status vocabulary and rules are in [traceability.md](traceability.md) (Specified, Implemented, Verified, Gap, Blocked). Evidence rules, in short:

- A test file, a test name or a test count is not evidence.
- Verified needs a dated execution record that matches the requirement's scope and environment.
- A closed phase, an accepted task or a previous report claiming completion does not change a requirement's status. Local PostgreSQL never verifies a requirement that names Neon (SDD-D-2).
- Missing historical evidence is recorded as `unknown` or `unverified`, never reconstructed.

## 7. Changing specifications and decisions

- Never silently modify an approved spec. If implementation and spec conflict, write a change proposal (a task of type spec change with the proposed text) and stop for owner review.
- A spec change that alters a requirement records the old and new text in the task, keeps the ID, and updates traceability. If the change affects verified work, the affected rows return to `Gap` until re-verified.
- Architecture-level choices are recorded in [decisions.md](decisions.md) as `SDD-D-n`, or in the owning spec's own namespace if the module introduced one (AI Platform `D-n`). A new decision never overrides an existing one; supersede it explicitly and cite it.
- Historical discrepancies (for example a missing decision number) are listed in [decisions.md](decisions.md) section 6 and tracked by a task. They are not repaired by guessing.

## 8. Reusable workflows

Skills under `.claude/skills/` implement this process. They contain procedure only and defer to the repository rules.

| Skill | Use |
| --- | --- |
| `sdd-analyze-spec` | Read a module spec, list its requirement IDs, decisions and traceability state |
| `sdd-prepare-task` | Create or update a task file and propose it as `Ready` |
| `sdd-implement` | Implement a `Ready` task with requirement-tagged tests and commits |
| `sdd-verify` | Record execution evidence and update traceability |
| `sdd-close-milestone` | Check the milestone, validate docs, and stop for owner review |
| `sdd-kickoff-phase` | Read-only check of whether a phase is ready to start; proposes tasks, creates none |
| `sdd-arch-check` | Module boundaries, import cycles, table ownership and decision coverage, using the DB-free architecture tests |
| `run-db-suite` (existing) | The only way to run the database suite. Unchanged |

Read-only reviewer agents for section 11 are in `.claude/agents/`: `spec-auditor`, `pm-reviewer`, `architect-reviewer`, `ai-reviewer`.

## 9. Risk-tiered review gates (SDD-D-8)

New wording, approved by the owner on 2026-11-20 through T-012.

- **Plan approval is always required** before work starts. A `Ready` task is that approval.
- **Result review is always required, before the next task starts,** for a task that changes any of: database migrations; contracts (public service interfaces, API or OpenAPI schemas, event contracts); authentication or security behavior; dependencies (`pyproject.toml`, `uv.lock`, CI actions); ADRs; AI targets (model catalog, thresholds, eval datasets, the task registry).
- **For every other task,** result review happens at milestone end (SDD-D-4 unchanged for these).
- The author classifies the task in its "Review and approval" section. The owner may raise the tier. A task that touches several tiers takes the strictest one.

## 10. Evidence-based reporting

New wording, approved 2026-11-20 (T-012).

- A report that claims verification states, for each command: the exact command line (secrets omitted), exit code, counts (passed, failed, skipped, errors), environment, and date.
- Anything that was not executed is written `NOT RUN`, with the reason. Phrases such as "should pass" or "presumably" are not used.
- `Verified` in [traceability.md](traceability.md) needs an Evidence cell that links to a dated record containing those fields (a file in `docs/reports/` or a task Evidence section). A row without a link is not `Verified`.

## 11. Independent audit

New wording, approved 2026-11-20 (T-012).

- Before a task moves to `Verified` or goes to owner review, a read-only reviewer in a fresh context audits it. The reviewer receives the task, the spec text, the diff and the evidence records, and does not receive the author's conclusions.
- Reviewers are the agents in `.claude/agents/`: `spec-auditor` always; `pm-reviewer`, `architect-reviewer` and `ai-reviewer` where their area applies.
- The audit reports **PASS, PARTIAL or FAIL for each acceptance criterion**, each with the evidence it relied on. PARTIAL and FAIL block `Verified`. An audit changes no status; the author of the evidence and the owner do.
- The implementing session never audits its own task.

## 12. Safety tiers

New wording, approved 2026-11-20 (T-012). Adds to, and never relaxes, the Standing rules.

- **Allowed without asking:** read-only inspection; DB-free tests, `ruff`, `mypy`; the local database suite through `/run-db-suite`; `git add`, `git commit` and non-force `git push` on the working branch.
- **Ask first:** dependency changes; any Neon access; deploys; destructive operations (`rm -rf`, `git clean`, force push, dropping a database); paid or real-provider API calls; handling secrets; editing an approved spec; running downloaded code.
- **Never:** the agent starting the Docker daemon; reading `.env*` files; printing secret values; Neon through MCP (denied in `.claude/settings.json`); force push.
- **Docker:** the agent never starts the daemon. `scripts/run_db_suite.sh` may create and remove only the container `strativa-test-db`, with a fixed container name and port (`127.0.0.1:55444`, see `compose.test-db.yaml`), no `volume`, `prune` or `system` commands, and no non-local target (refused by `require_local_test_targets` in local mode). Checked by reading on 2026-11-20: the script itself contains no explicit non-local check; the guard does.

## 13. Eval gate for AI task specs

New wording, approved 2026-11-20 (T-012).

- No spec that defines an AI task may be approved without measurable thresholds and a hand-labeled golden set, as described in [evals/README.md](evals/README.md).
- Not retroactive: `ai_platform` is infrastructure and defines no domain AI task (D-6). The rule applies to the first domain spec that does (for example `brief`, `signal_synthesizer`).
