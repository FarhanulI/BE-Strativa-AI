# AI evals

This is the eval contract. It defines the format and the gate, not thresholds. **No threshold is set yet:** each AI task spec states its own (owner decision, 2026-11-20).

## Gate (proposed rule, applied only after T-012 is approved)

No specification that defines an AI task may be approved without:
1. **Measurable thresholds**: named metrics with numeric pass criteria, stated in the task spec.
2. **A hand-labeled golden set**: cases labeled by a person (the owner or a named delegate), versioned, and committed or referenced by path.

Not retroactive: `ai_platform` is infrastructure and defines no domain AI task (D-6). The gate applies to the first domain spec that does.

## Golden set rules

- Synthetic text only. No real user content, ever, until the privacy review is recorded (D-27).
- Each case records who labeled it and when. A model never labels its own golden set.
- A change to labels is a new set version; old versions stay.
- A case must not appear in any prompt, few-shot example or training material of the task under test.

## Case format (JSON Lines, one object per line)

```json
{
  "case_id": "brief-0001",
  "task": "GENERATE_CONTENT_BRIEF",
  "set_version": 1,
  "input": {"instructions_version": "example-1", "context_blocks": ["synthetic text"]},
  "expected": {"checks": [{"name": "has_hook", "pass": true}]},
  "labeled_by": "name or role",
  "labeled_at": "YYYY-MM-DD",
  "notes": ""
}
```

Field names are illustrative until the first AI task spec fixes them.

## Run record (what every eval run writes down)

Date; commit; task; golden set version; `instructions_version` (T-019); provider, model, `catalog_version`, `price_version` (from the usage ledger); per-metric results against the thresholds; p50 and p95 latency; cost; number of cases run, passed, failed; real-provider spend and the running total against the 20 USD cap (D-11, D-16). Anything not run is `NOT RUN` with the reason.

## Relation to existing checks

Strict output-schema validation and AC-60 (catalog fitness) check form and cost. They are not quality evals.

## Review

The `ai-reviewer` agent (`.claude/agents/ai-reviewer.md`) checks that a spec meets this gate. Result review is always required for AI targets (T-012, P-1).
