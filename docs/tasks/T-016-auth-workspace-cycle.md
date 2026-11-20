# T-016: auth and workspace dependency cycle (check, then fix)

- **Module and phase:** auth, workspace, api_contract (composition root); Phase 1 and Phase 0
- **State:** Proposed
- **Requirement IDs:** CORE-INV-11, WS-AC-7 (the boundary rules the check strengthens); AUTH-AC-2 and AUTH-AC-7 (must stay satisfied by the fix)
- **Specification references:** [auth-onboarding](../specs/auth-onboarding/spec.md) (registration calls `WorkspaceService.create_workspace_for_owner(session, user_id, name)` in the caller-owned transaction; `/me` reads roles through the workspace public interface); [workspace](../specs/workspace/spec.md); [conformance report](../architecture/conformance-report.md) B-1 (corrected 2026-11-20); ADR-0003 (proposed)
- **Dependencies:** A recorded baseline run of the auth and workspace DB tests before any change (step 0), from T-003 or from this task. T-013 preferred. Owner decisions of 2026-11-20: dependency inversion at the composition root; the protocol takes the caller's session or unit of work; the cycle check includes function-level imports; owner review between step 1 and step 2.

## Objective
Make the package import graph acyclic without changing observable behavior: registration stays one transaction (AUTH-AC-2), `/me` still reads roles through the workspace public interface (AUTH-AC-7).

## Scope
**Step 0, baseline.** Run the auth and workspace DB tests through `/run-db-suite` and the DB-free suite before touching code. Record the result (T-014 format). Stop if the baseline is red.

**Step 1, cycle check (tests only; review follows).**
- Add a DB-free architecture test that builds the package-level import graph of `app/` from the AST and fails on any cycle.
- It must include imports inside functions and methods (such as the lazy import in `app/auth/__init__.py:register_routes`), not only module-level imports. String-based dynamic imports are out of scope and the limit is stated in the test.
- Landing it on a red tree is not allowed. The one known cycle (auth and workspace) is listed in a visible allowlist that names this task and step 2; step 2 removes the entry.
- Stop for owner review.

**Step 2, fix (after review).**
- `auth` defines protocols that receive the caller's `AsyncSession` (or unit of work) and return what auth needs: a workspace provisioner for registration, and a role reader for `/me`. Auth imports no `app.workspace` name.
- `workspace` implements them; `workspace` keeps depending on `auth` for `get_current_user` (the one remaining direction).
- `api_contract.create_app` wires the implementations into `auth` when routes are registered; the lazy import disappears.
- The allowlist entry is removed; ADR-0003 is updated from proposed to the recorded decision.

## Non-goals
Any change to behavior, routes, OpenAPI, events or schema. Editing any spec. Using the outbox or any asynchronous mechanism for registration. Fixing B-2 or B-3 (ORM export and table-ownership checks). Other module pairs.

## Implementation expectations
If, during step 2, the spec wording of AUTH-AC-2 or AUTH-AC-7 turns out to require a direct import, stop and write a change proposal. Boundaries: protocols live in `auth`; no new cross-module import other than through package exports. Commits cite T-016, the step and the IDs.

## Required tests
- Step 1: the cycle test (fails on a seeded cycle in a fixture, passes on the allowlisted tree).
- Step 2: the existing registration and `/me` DB tests unchanged, including the rollback test for AUTH-AC-2, plus `test_checked_in_openapi_matches_registered_routes` (OpenAPI must not change), the boundary test, and the cycle test with the allowlist empty.

## Verification requirements
Before and after runs with exact commands, exit codes and counts. DB tests only through `/run-db-suite`. The after-run must equal the baseline except for the added test.

## Acceptance criteria
- The cycle test exists, sees function-level imports, and with an empty allowlist passes.
- AUTH-AC-2 and AUTH-AC-7 tests pass before and after with the same counts.
- No `app.auth` file imports `app.workspace`.
- OpenAPI output is unchanged.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: always** (auth behavior; contracts). Owner review after step 1 and after step 2.
