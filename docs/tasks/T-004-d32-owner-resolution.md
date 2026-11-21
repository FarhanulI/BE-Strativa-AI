# T-004: D-32 owner resolution

- **Module and phase:** ai_platform, Phase 2
- **State:** Blocked
- **Requirement IDs:** None. Dependency: AI Platform decision D-32, referenced but not defined (see [decisions.md](../decisions.md) section 6).
- **Specification references:** [AI Platform spec, section 20.1](../specs/ai-platform/spec.md)
- **Dependencies:** Owner decision.

## Objective
Obtain the owner's resolution of the D-32 reference discrepancy: an intentional numbering gap, a lost decision, or a stale code reference.

## Scope
Record the owner's answer in decisions.md. If the owner supplies decision text, add it to the spec through a change proposal (SDD rule 4).

## Non-goals
Creating, guessing or inferring a D-32. Renumbering D-33 onward. Editing the existing code or test references without owner direction.

## Implementation expectations
Documentation only, unless the owner directs a code comment change.

## Required tests
None.

## Verification requirements
The owner's recorded answer and date.

## Acceptance criteria
The discrepancy is closed with an owner-attributed record.

## Evidence
None recorded. Known references: `app/ai_platform/failure_policy.py`, `tests/unit/ai_platform/test_failure_policy.py`.

## Review and approval
Not requested.
