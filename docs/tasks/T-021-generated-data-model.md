# T-021: Generated data model document and drift gate

- **Module and phase:** db_migrations, Phase 0
- **State:** Proposed
- **Requirement IDs:** DBM-AC-3 (DB-free metadata test; the new test follows the same approach). Other `DBM-INV-n` and `DBM-AC-n` IDs are chosen from the spec when the task is prepared; none is assumed here.
- **Specification references:** [db-migrations](../specs/db-migrations/spec.md); [conformance report](../architecture/conformance-report.md) C-1, C-2
- **Dependencies:** T-013 (so the gate runs automatically). Owner approval of the output format.

## Objective
Provide one reference description of the physical schema that cannot drift from the code, instead of a hand-written copy.

## Scope
- A script that reads `Base.metadata` (after the model modules are imported, as `alembic/env.py` does) and writes `docs/architecture/data-model.md` deterministically: table, owning module (from the package that defines it), tenant scope (`info["tenant_scope"]`), columns with types and nullability, constraints, indexes, foreign keys.
- A DB-free test that regenerates the content in memory and fails when the committed file differs.
- Specs stay normative for intent; the generated file is a reference only and says so in its header.

## Non-goals
Connecting to any database. Documenting views or non-ORM objects. Replacing the module specs. Business descriptions of columns.

## Implementation expectations
No database or network access; stable ordering; no timestamps in the output. The script lives under `scripts/` and follows the existing script conventions. If the owning-module mapping cannot be derived from the metadata alone, the mapping rule is stated in the task before implementation.

## Required tests
The drift test, a determinism test (two runs produce identical bytes), and the existing metadata classification test unchanged.

## Verification requirements
Commands, exit codes and counts (T-014 format); the CI run from T-013.

## Acceptance criteria
The generated file is committed and current; changing a model without regenerating makes the test fail; the output is deterministic.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: milestone end.**
