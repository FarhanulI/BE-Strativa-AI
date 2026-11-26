# ADR-0004: Cross-module foreign keys and delete policy

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** D-17; conformance finding B-4; the ownership rules in the copilot instructions.

## Context

Tables reference tables owned by other modules.

## Decision (as observed or as decided)

Foreign keys cross module ownership: `workspace_members.user_id` (CASCADE), `workspace_invitations.invited_by_user_id` (RESTRICT), `content_profiles.workspace_id` (CASCADE), `ai_requests.requested_by_user_id` (SET NULL), and `ai_requests`, `ai_usage_records`, `ai_budget_periods` to `workspaces` (CASCADE). A foreign key is not a query, so the boundary rule is not broken.

## Rationale

D-17 accepts `ON DELETE CASCADE` on `ai_*` foreign keys 'for now'. The profile spec follows the same pattern for `content_profiles`. No single statement covers all modules, and the effect of deleting a workspace on the cost ledger (`ai_usage_records`) is not discussed.

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
