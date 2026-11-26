# T-010: Frontend normative scope and spec cleanup questions

- **Module and phase:** auth and profile, Phase 1
- **State:** Blocked
- **Requirement IDs:** None assigned. Dependency: scope decision for the Auth "Response and cookie contract", "BFF session and entry routing", "Derived onboarding wizard" and "Frozen design notes" sections, and the Profile "Concurrency and error handling" section.
- **Specification references:** [auth-onboarding](../specs/auth-onboarding/spec.md), [profile](../specs/profile/spec.md)
- **Dependencies:** Owner decision; frontend scope.

## Objective
Decide which frontend-section statements, if any, are normative requirements, and where they belong (backend spec or a frontend spec).

## Scope
Questions to answer:
1. Is the Auth cookie and BFF material normative for the backend? AUTH-INV-6 already covers cookie attributes.
2. Which Profile frontend concurrency statements are normative, given PROF-INV-4 covers the backend `If-Match` behavior?
3. Onboarding stays frontend-derived state and is not a backend module. Confirm.
4. Line 1 of the Auth spec is a stray `PATCH /me` table row above the title. Confirm whether to remove it.

## Non-goals
Converting design material into acceptance criteria before the scope is decided. Editing `../web`.

## Implementation expectations
Documentation only, after the owner answers.

## Required tests
None.

## Verification requirements
Owner-attributed decisions.

## Acceptance criteria
Each question has a recorded answer. Any new IDs take the next free number.

## Evidence
None recorded.

## Review and approval
Not requested.
