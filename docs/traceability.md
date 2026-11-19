# Traceability Matrix

This document is the initial traceability **framework**. It defines the schema, the status vocabulary and the rules. It does not yet map any requirement.

## 1. Initial notes

- **Phase 1 is owner-declared closed** (SDD-D-1 in [decisions.md](decisions.md)). That is a delivery-status decision. Requirement-level verification evidence for Phase 1 remains subject to retrospective traceability and to the required Neon TEST-branch verification (SDD-D-2). No Phase 1 requirement is `Verified` merely because the phase is closed.
- This milestone does not assign requirement IDs, edit specifications or populate mappings. The matrix in section 5 is intentionally empty.
- The matrix does not claim that all requirements are covered.

## 2. Schema

| Field | Meaning |
| --- | --- |
| Requirement ID | Stable AC or INV identifier, exactly as written in the source spec |
| Module | Owning module (names as in [modules.md](modules.md)) |
| Spec | Source specification file |
| Spec section | Exact section containing the requirement |
| Implementation | Relevant source file or symbol |
| Test | Relevant test file and test name |
| Evidence | Dated test execution or report reference |
| Status | One of Specified, Implemented, Verified, Gap, Blocked |
| Notes | Missing evidence, limitations or explanation |

## 3. Status definitions

| Status | Meaning | Minimum required to use it |
| --- | --- | --- |
| Specified | The requirement exists in an approved or draft spec. No implementation is claimed. | Spec and spec section filled |
| Implemented | Implementation exists and is identified. No passing test run is claimed. | Implementation reference filled |
| Verified | A mapped test or demonstrated workflow was executed and passed, and the result is recorded with a date. | Test and Evidence both filled, and Evidence includes the execution date |
| Gap | The requirement is not met, not mapped, or the evidence is missing or unsatisfactory, and no blocker is known. | Notes state what is missing |
| Blocked | Verification or implementation cannot proceed until a named dependency is resolved. | Notes name the blocker |

## 4. Rules

1. **Verified requires dated execution evidence.** Evidence must be a recorded test run or verification report with a date. A requirement without that evidence cannot be `Verified`.
2. A test file existing is not proof that a test passed.
3. A count of test functions is not proof of conformance to a requirement.
4. A passing run on a different environment than the one the requirement names does not count. For example, local PostgreSQL does not verify a criterion that names a Neon TEST branch (SDD-D-2).
5. A missing mapping stays explicitly **unmapped**. Write `unmapped` in the cell. Do not leave it blank and do not guess.
6. Do not fill Implementation or Test with speculative references. Only record references that were inspected.
7. Preserve the AC and INV identifiers used in the source specs. Do not renumber them.
8. If a spec has no stable ID for a requirement, record that as a note. Assigning IDs is done in a later, owner-approved milestone, not here.
9. Evidence must not be invented, back-dated or copied from a different run. A report dated earlier cannot verify behavior that changed afterwards.
10. Closing a phase does not change a requirement's status.
11. Status changes are reviewed by the owner at milestone level.

## 5. Matrix

No rows yet. Rows are added only with inspected references and, for `Verified`, dated evidence.

| Requirement ID | Module | Spec | Spec section | Implementation | Test | Evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _none recorded_ | | | | | | | | |

## 6. Known specification identifier situation

Observed in the specs at the time of writing. This is information for later milestones and changes nothing.

| Spec | Identifier situation |
| --- | --- |
| [AI Platform](specs/ai-platform/spec.md) | Uses `INV-n` (section 16) and `AC-n` (section 17), with an invariant-to-AC mapping in section 17.7. |
| [Workspace](specs/workspace/spec.md) | Invariants and acceptance criteria are bullet lists without stable IDs. |
| Other modules | Not inspected in this milestone. |

## 7. Open verification items recorded so far

| Item | Source | State |
| --- | --- | --- |
| Concurrent demotion/removal cannot leave a workspace without an OWNER, on a real Neon TEST branch | [Workspace spec, Acceptance criteria](specs/workspace/spec.md) | Required (SDD-D-2). Not evidenced here. Needs a separately authorized Neon task. |
