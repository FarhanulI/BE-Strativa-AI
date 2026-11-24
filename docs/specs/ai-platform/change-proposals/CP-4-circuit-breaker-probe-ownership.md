# CP-4: Circuit breaker probe ownership and lease (change proposal for the AI Platform spec)

- **Status:** Approved by the owner 2026-11-24 ("owner decisions, this conversation"), together with decision D-37, AC-64, AC-65 and a separate task T-022 (state Proposed). Applied as spec revision 11. No code, test or configuration was changed by this proposal.
- **Raised by:** the read-only Step 5 verification of task [T-011](../../../tasks/T-011-ai-platform-sync-run-path.md) (findings H1, H2 and M1). T-011's scope and historical record are unchanged.
- **Spec revision it amends:** revision 10, producing revision 11. Section 10.4, one new decision (D-37), AC-64 and AC-65 in section 17.2, and a note in section 17.7.
- **Rule:** SDD rules 4 and 15. A clarification of an approved spec is still a change proposal, and the owner approves it.

## Why

Section 10.4 says one probe goes through and its success closes the breaker, its failure re-opens it. The code decides "this is the probe" from state and elapsed time, not from the caller.

- **H1.** `abandon_attempt(key)` clears the probe claim of the model whoever owns it. A request that already released its probe, or that started while the breaker was closed, can wipe a newer probe's claim, and a second concurrent probe then starts. Outcomes are also attributed by state and time, not by handle.
- **H2.** A probe is treated as lost after `breaker_open_seconds` (30 s), but a call may run 60 s or 300 s. After 30 s the probe's own success no longer closes the breaker and its failure no longer re-opens it.
- **M1.** No orchestrator-level test shows that a refused reservation or an unexpected exception releases a claimed probe.

## Proposed text (applied in revision 11)

- **Section 10.4:** three paragraphs appended after the existing one (attempt handles and probe ownership, probe lease, internal failures).
- **Decision D-37** in the decision table of section 20.1 (the specification owns it; it is not copied to `docs/decisions.md`).
- **AC-64** (registry ownership and lease, DB-free) and **AC-65** (orchestrator probe cleanup, DB) at the end of section 17.2. Neither is mapped to a numbered invariant. Section 17.7 carries a note saying so, in the same way as for AC-60. INV-22 is unchanged.

## Owner decisions applied

| Question | Decision |
| --- | --- |
| Lease margin (Q1) | `probe_lease_seconds = longest_deadline_seconds + 30`. The 30 s margin is a fixed internal constant, not `breaker_open_seconds` and not an environment variable. No hard `asyncio` timeout is added. The adapter timeout limitation and the interaction with the async worker path (T-008) are follow-up considerations recorded in T-022. |
| Acceptance criteria (Q2) | AC-64 and AC-65 are separate. AC-20 is not overloaded and is unchanged. |
| T-011 evidence (Q3) | T-011's historical evidence stays as written. T-022 documents that the handle API supersedes the earlier boolean API. |
| M1 tests (Q4) | All remediation tests stay in T-022. T-011 step 5 is not reopened. |
| Review tier (Q5) | Gate `always` for T-022, with five checkpoints (see the task). |

## Deviation from the first draft

The first draft derived the lease margin from `breaker_open_seconds`. The owner replaced it with a fixed 30 s margin. This proposal and the spec text use the fixed margin. `longest_deadline_seconds` was checked in the code before this was written: it is a property of `AiPlatformConfig` ([config.py:228](../../../../app/ai_platform/config.py#L228)), the maximum of the interactive, standard and batch deadlines, and the existing `sync_stale_after_seconds` validator already relies on it. It is therefore a reliable input.

## Impact

- **Requirements:** AC-20 and D-35 keep their meaning and status. AC-64 and AC-65 are new and `Specified`. No ID is reused or renumbered.
- **Configuration:** none. No new setting and no `.env`, `.env.example` or `.env.local` change.
- **Existing data:** none (in-memory state).
- **Security and privacy:** no event or log field name contains "token" (INV-18); the handle field is `claim_id`. Logged transition fields stay provider, model, state and failure count.
- **Scope:** circuit breaker, config property and orchestrator wiring, all in task T-022, which is `Proposed` and not `Ready`.
