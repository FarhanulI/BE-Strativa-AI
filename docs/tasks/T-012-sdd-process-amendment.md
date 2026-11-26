# T-012: SDD process amendment (change proposal, documentation only)

- **Module and phase:** Not applicable (SDD process); applies to every phase
- **State:** Accepted (owner approved P-1 to P-6 as drafted and accepted the result on 2026-11-20)
- **Requirement IDs:** None. This task changes process documents, not a module specification. It supersedes SDD-D-4 in part through a new decision, SDD-D-8, following [sdd.md](../sdd.md) section 7.
- **Specification references:** [sdd.md](../sdd.md) sections 4 to 8; [decisions.md](../decisions.md) SDD-D-4; [.github/copilot-instructions.md](../../.github/copilot-instructions.md) rules 1 to 17; [conformance report](../architecture/conformance-report.md)
- **Dependencies:** Owner approval. **SDD-D-4 stays in force until the owner approves this task.** Nothing below is applied to `sdd.md`, `copilot-instructions.md` or `decisions.md` before that approval.

## Objective
Add the policy items that the existing SDD documents do not yet contain, as one reviewable change: risk-tiered review gates, evidence-based reporting with a literal `NOT RUN`, an independent fresh-context audit, tiered safety rules, and the eval gate for AI task specs. Add only what is missing; do not restate existing rules.

## Overlap found (what already exists and is not repeated)
| Item | Already in | Missing |
| --- | --- | --- |
| Evidence needs date, command, environment, counts | copilot rule 14; `sdd-verify` step 3; traceability rules 1 to 9 | Exit codes; the literal `NOT RUN`; a link to the evidence record |
| Owner review | SDD-D-4 (milestone granularity); sdd.md section 4 step 8 | Risk tiers, so that high-risk results are reviewed at once |
| Read-only checks | `sdd-analyze-spec`, `sdd-close-milestone` (author's own context) | Independent review with PASS / PARTIAL / FAIL per criterion |
| Prohibitions | Standing rules; copilot rules 9, 16, 17 | A tiered list of what is allowed, what asks first, what is never done |
| AI quality | Nothing | An eval gate for AI task specs |

## Proposed wording (new wording, flagged for owner review)

### P-1. Risk-tiered gates (new `sdd.md` section 9; new rule 18; new decision SDD-D-8)
- **Plan approval is always required** before work starts. A `Ready` task is that approval.
- **Result review is always required, before the next task starts,** for a task that changes any of: database migrations; contracts (public service interfaces, API or OpenAPI schemas, event contracts); authentication or security behavior; dependencies (`pyproject.toml`, `uv.lock`, CI actions); ADRs; AI targets (model catalog, thresholds, eval datasets, the task registry).
- **For every other task,** result review happens at milestone end (SDD-D-4 unchanged for these).
- The author classifies the task in its "Review and approval" section. The owner may raise the tier. A task that touches several tiers takes the strictest one.
- **SDD-D-8 text:** "Supersedes SDD-D-4 in part. Owner result review is per task for the categories in P-1 and per milestone for all other tasks. SDD-D-4 is unchanged for tasks outside those categories and remains in force for them."

### P-2. Evidence-based reporting (new `sdd.md` section 10; new rule 19)
- A report that claims verification states, for each command: the exact command line (secrets omitted), exit code, counts (passed, failed, skipped, errors), environment, and date.
- Anything that was not executed is written `NOT RUN`, with the reason. Phrases such as "should pass" or "presumably" are not used.
- `Verified` in [traceability.md](../traceability.md) needs an Evidence cell that links to a dated record containing those fields (a file in `docs/reports/` or a task Evidence section). A row without a link is not `Verified`.

### P-3. Independent audit (new `sdd.md` section 11; new rule 20)
- Before a task moves to `Verified` or goes to owner review, a read-only reviewer in a fresh context audits it. The reviewer receives the task, the spec text, the diff and the evidence records, and does not receive the author's conclusions.
- Reviewers are the agents in `.claude/agents/` (`spec-auditor` always; `pm-reviewer`, `architect-reviewer`, `ai-reviewer` where their area applies).
- The audit reports **PASS, PARTIAL or FAIL for each acceptance criterion**, each with the evidence it relied on. PARTIAL and FAIL block `Verified`. An audit changes no status; the author of the evidence and the owner do.
- The implementing session never audits its own task.

### P-4. Safety tiers (new `sdd.md` section 12; new rule 21)
- **Allowed without asking:** read-only inspection; DB-free tests, `ruff`, `mypy`; the local database suite through `/run-db-suite`; `git add`, `git commit` and non-force `git push` on the working branch.
- **Ask first:** dependency changes; any Neon access; deploys; destructive operations (`rm -rf`, `git clean`, force push, dropping a database); paid or real-provider API calls; handling secrets; editing an approved spec; running downloaded code.
- **Never:** the agent starting the Docker daemon; reading `.env*` files; printing secret values; Neon through MCP (denied in `.claude/settings.json`); force push.
- **Docker, reconciling the `run-db-suite` and `sdd-verify` wording:** the agent never starts the daemon. `scripts/run_db_suite.sh` may create and remove only the container `strativa-test-db`. Constraints on that script: fixed container name and fixed port (`127.0.0.1:55444`, see `compose.test-db.yaml`); refuse non-local targets; no `volume`, `prune` or `system` commands.
  - Checked 2026-11-20 by reading: the compose file fixes the name and the loopback port; the script runs only `docker info`, `docker ps`, `docker rm -f strativa-test-db` and `docker compose up/down`; `app/db_migrations/guard.py` calls `require_local_test_targets` in local mode. The script itself contains no explicit non-local check; the guard does.

### P-5. Eval gate for AI task specs (new `sdd.md` section 13; new rule 22)
- No spec that defines an AI task may be approved without measurable thresholds and a hand-labeled golden set, as described in [docs/evals/README.md](../evals/README.md).
- Not retroactive: `ai_platform` is infrastructure and defines no domain AI task (D-6). The rule applies to the first domain spec that does (for example `brief`, `signal_synthesizer`).

### P-6. Index changes
- `sdd.md` section 8 table gains `sdd-kickoff-phase` and `sdd-arch-check`, and a pointer to `.claude/agents/`.
- `docs/tasks/README.md` is updated by this scaffolding step, not by this task.

## Scope
Draft the wording above, list the exact edits, and apply them to `sdd.md`, `copilot-instructions.md` and `decisions.md` only after the owner approves this task.

## Non-goals
Changing any module specification. Changing SDD-D-1 to SDD-D-7. Editing `run_db_suite.sh` or any skill (a script or skill change would be its own task). Enforcement tooling.

## Implementation expectations
After approval: one commit per document, each citing T-012 and SDD-D-8. `decisions.md` records SDD-D-8 with date and status, and states which part of SDD-D-4 it supersedes. SDD-D-4 text is not edited.

## Required tests
None (documentation). `sdd-close-milestone` checks run after the edit.

## Verification requirements
`sdd-close-milestone` link and consistency checks, with the exact commands and results recorded. Anything not run is stated as `NOT RUN`.

## Acceptance criteria
- The owner has approved or amended each of P-1 to P-6.
- If approved, the three documents contain the wording, SDD-D-4 is untouched, and no existing rule is duplicated.

## Evidence
- 2026-11-20: P-1 to P-5 applied to [sdd.md](../sdd.md) sections 9 to 13 and rules 18 to 22 of copilot-instructions; P-6 applied to sdd.md section 8; SDD-D-8 recorded in [decisions.md](../decisions.md). SDD-D-4 text not edited. Three consistency edits beyond the proposed wording, to avoid contradicting the new rules: sdd.md step 8 and the intro line (SDD-D-1 to SDD-D-8), and copilot rule 8 each point to the new sections.
- 2026-11-20, local, ad-hoc relative-link check over the 6 changed markdown files (`python check_links.py`, a scratchpad script that is not in the repo): exit 0, 94 links checked, 0 broken; `.claude/settings.json` parsed as valid JSON. This is not a `sdd-close-milestone` run: `sdd-close-milestone` is NOT RUN.

## Review and approval
Plan and wording approved by the owner on 2026-11-20. **Gate: always** (governance). Owner accepted the result on 2026-11-20. Independent audit (section 11): NOT RUN (the owner chose to proceed without it).
