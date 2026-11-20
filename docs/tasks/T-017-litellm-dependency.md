# T-017: Add and pin the LiteLLM dependency

- **Module and phase:** ai_platform, Phase 2
- **State:** Proposed
- **Requirement IDs:** INV-1 and AC-1 (provider SDK imports confined to `app/ai_platform/`). This task is a prerequisite for the adapter and does not change their status.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) section 1 (provider abstraction through LiteLLM), INV-1, AC-1, D-21, D-22, section 20.4; [conformance report](../architecture/conformance-report.md) F-4
- **Dependencies:** T-013 (CI) so that the lock change is tested on a clean install. Owner approval at each stop below. **Always-stop gate: this task never proceeds from one stop to the next without the owner.**

## Objective
Declare LiteLLM as a dependency with an exact version and a reproducible lock, with no application code using it yet.

## Scope
**Stop 1, proposal.** Present the candidate exact version with: release date and age, license, published security advisories at that date, the full list of new transitive packages (names and versions) from a dry-run resolution, and the impact on install size. Run nothing that changes the repository.
**Stop 2, change.** After approval: add `litellm==<exact version>` to `pyproject.toml`, regenerate `uv.lock`, commit both. Show the lock diff (added and changed packages) to the owner.
**Stop 3, check.** Run the DB-free suite, the architecture tests (INV-1 and AC-1 boundary test, provider identifier tests) and a clean `uv sync --locked`, and report.

## Non-goals
Any `import litellm` in `app/`. The provider adapter, a real provider call, key handling (D-22), any catalog data (T-018). Upgrading other dependencies. Verifying the Perplexity decoding questions listed in spec 20.4; those belong to the adapter task and need the installed version this task provides.

## Implementation expectations
The version is chosen only from information fetched in the session (package index and release notes), not from memory. No `uv add` or lock command runs before stop 2 is approved. The owner decides the version.

## Required tests
Existing architecture tests unchanged and passing. `uv sync --locked` succeeds from a clean environment.

## Verification requirements
Command lines, exit codes and counts for stop 3, with the dependency evidence from stop 1 attached to the record (T-014 format). Items not run are `NOT RUN`.

## Acceptance criteria
- `pyproject.toml` pins the exact version and `uv.lock` matches.
- No file under `app/` imports `litellm`.
- The architecture tests pass; the lock diff was reviewed by the owner.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: always** (dependency).
