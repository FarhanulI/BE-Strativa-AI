# Tasks

A task is a bounded, owner-approved unit of work. The process, lifecycle and rules are in [../sdd.md](../sdd.md). Task IDs (`T-nnn`) are separate from requirement IDs. A task cites requirement IDs; it never replaces them.

## Index

| Task | Title | Module / phase | State | Blocker or dependency |
| --- | --- | --- | --- | --- |
| [T-001](T-001-workspace-neon-concurrency.md) | Workspace Neon TEST-branch concurrency verification | workspace / 1 | Blocked | Separate explicit owner authorization to run on Neon (SDD-D-2) |
| [T-002](T-002-phase0-reverification.md) | Phase 0 re-verification | Phase 0 modules / 0 | Proposed | Owner approval; real Redis; Neon only under separate authorization |
| [T-003](T-003-phase1-retrospective-verification.md) | Phase 1 retrospective verification gaps | auth, workspace, profile / 1 | Proposed | T-001 for WS-AC-3; owner approval |
| [T-004](T-004-d32-owner-resolution.md) | D-32 owner resolution | ai_platform / 2 | Blocked | Owner decision |
| [T-005](T-005-d20-revision-metadata.md) | D-20 revision metadata investigation | ai_platform / 2 | Blocked | New evidence (history) not available |
| [T-006](T-006-ai-platform-approval-clarification.md) | AI Platform revision 5 to 7 approval clarification | ai_platform / 2 | Blocked | Owner confirmation |
| [T-007](T-007-web-foundation-spec-dependency.md) | web_foundation specification dependency | web_foundation / 0 | Blocked | Frontend task must provide the spec |
| [T-008](T-008-ai-platform-remaining-verification.md) | Remaining AI Platform implementation and verification gaps | ai_platform / 2 | Proposed | T-004 and T-006 for governance; feature work waits for owner approval to resume (SDD-D-3) |
| [T-009](T-009-nine-spec-approval-metadata.md) | Approval metadata for the nine non-AI-Platform specs | Phase 0 and 1 modules | Blocked | Owner confirmation |
| [T-010](T-010-frontend-scope-questions.md) | Frontend normative scope and spec cleanup questions | auth, profile / 1 | Blocked | Owner decision; frontend scope |

No task exists for a module that has no specification.

## Template

Copy this for a new task. Every field is required; write `None` or `Not applicable` explicitly rather than leaving a field out.

```markdown
# T-nnn: Title

- **Module and phase:**
- **State:** Proposed | Ready | In Progress | Implemented | Verified | Accepted | Blocked
- **Requirement IDs:** (valid IDs from the spec, or "None: dependency on ...")
- **Specification references:**
- **Dependencies:**

## Objective
## Scope
## Non-goals
## Implementation expectations
## Required tests
## Verification requirements
## Acceptance criteria
## Evidence
(Dated execution records only. "None recorded" until work is executed.)
## Review and approval
(Owner approval state and date. "Not requested" until review.)
```
