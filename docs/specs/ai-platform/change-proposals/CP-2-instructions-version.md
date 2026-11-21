# CP-2: `instructions_version` on AI task requests (change proposal for the AI Platform spec)

- **Status:** Proposed (not applied; the approved spec is unchanged). The owner confirmed the design points on 2026-11-21: label is part of the canonical request, SDD-Q-4 constraints, a database CHECK, recorded as decision `D-36`. The exact text below awaits approval.
- **Raised by:** task [T-019](../../../tasks/T-019-instructions-version.md); conformance finding F-2.
- **Spec revision it would amend:** revision 8, producing revision 9. Sections 4.1, 5.1, 12.4, the decision table 20.1 (new `D-36`) and 17.5 (new `AC-62`, `AC-63`). Answers SDD-Q-4.
- **Rule:** SDD rules 4 and 15. Nothing in `spec.md` is edited until the owner approves this text.

## Why

D-6 says domain modules own and version their prompts, but nothing records which version produced a request. A change in quality, latency or cost cannot be traced to a prompt change, and evals cannot be attributed (F-2). A label is enough; storing or hashing prompt content is out of scope.

## Proposed text

**Section 4.1, new column of `ai_requests`**

| Column | Type | Notes |
| --- | --- | --- |
| `instructions_version` | text null | Opaque label chosen by the calling domain module for the trusted `instructions` text (D-6). A label, never content. Null for embedding rows and for rows created before revision 9. No backfill. |

New constraint: `ck_ai_requests_instructions_version`: `instructions_version IS NULL OR (char_length(instructions_version) BETWEEN 1 AND 64 AND instructions_version ~ '^[A-Za-z0-9._:-]+$')`.

**Section 4.1, `request_fingerprint` row.** Replace "SHA-256 over the canonical request" with: "SHA-256 over the canonical request, which includes `instructions_version` (null and absent are the same value)." The existing rule stays: the same key with a different fingerprint is a `Conflict` (so the same key with a different `instructions_version` is a `Conflict`).

**Section 5.1, `AiTaskRequest`.** New field `instructions_version: str | None = None`. Validation (reject, never truncate, never normalize): when present it is non-blank, 1 to 64 characters, and only letters, digits and `._:-`. The platform never interprets it, never derives it from content and never uses it to route (INV-2 is unaffected: it names no provider or model). The field name is the only thing an error message may carry, never the value.

**Section 12.4.** The value may appear in the logs `ai_call_started` and `ai_call_finished` and in audit details. It is not placed in any event payload until a consumer needs it, and then only through a versioned event change.

**Section 20.1, new decision.** `D-36` (new, rev 9): `instructions_version` is an optional, caller-supplied label stored on `ai_requests`; it is part of the canonical request for idempotency; it is nullable now and required-ness is a later change after a domain module calls the platform; it is validated in the request type and by a database CHECK with the same rule.

**Section 17.5, new acceptance criteria** (next free numbers; no ID renumbered)
- `AC-62`. Label validation and persistence (D-36, D-6). Unit: `AiTaskRequest` accepts `None` and valid labels (letters, digits, `._:-`, length 1 and 64) and rejects blank, whitespace-only, 65 characters, any other character (space, slash, non-ASCII) and non-strings, with an error that names the field and not the value. DB: a created request row stores the label and reads it back; a row with a label violating the rule is refused by `ck_ai_requests_instructions_version`; embedding and omitted-label rows are null. A replay of a submitted request with the same key and label returns the same request; the same key with a different label, or with and without a label, raises `Conflict`.
- `AC-63`. Migration `0009` (D-36). It adds the nullable column and the CHECK only, with no data change; upgrade, downgrade and upgrade again succeed on a database holding existing rows; `alembic check` reports no drift.

## Impact

- Existing requirements whose tests need updating, with no status change: AC-3 (the `AiTaskRequest` field list reflection), AC-10 and the `ai_requests` schema reflection tests, AC-39 (the fingerprint rule applies when the orchestrator exists in T-011; until then the repository tests cover only the stored column).
- No event, endpoint, usage-table or catalog change. `ai_usage_records` is untouched; metric views (T-020) reach the label through `request_id`.
- Migration `0009_ai_requests_instructions_version`, chained from `0008_ai_platform`. Additive and reversible.
- Not changed: prompt storage or hashing, required-ness, orchestrator (T-011).

## Owner decision requested

Approve the text above as revision 9? On approval, stop 2 applies it and implements the migration, model, request type, repository and tests, then asks you to run `/run-db-suite all`.
