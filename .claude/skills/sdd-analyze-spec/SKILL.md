---
name: sdd-analyze-spec
description: Read a module spec and report its requirement IDs, decisions, boundaries and traceability state before any task or implementation. Read-only.
argument-hint: <module, for example workspace>
allowed-tools: Read, Grep, Glob
---

Analyze one module for Spec-Driven Development. Follow [docs/sdd.md](../../../docs/sdd.md). Do not edit files.

1. Find the module in `docs/modules.md` (phase, neighbours). Open `docs/specs/<feature>/spec.md`.
2. Read the spec metadata (status, revision, approval). Report values exactly; if `Not stated`, say so.
3. List every requirement ID (`<MODULE>-INV-n`, `<MODULE>-AC-n`; AI Platform `INV-n`, `AC-n`) with a short paraphrase.
4. List the decisions that apply (`docs/decisions.md`, spec decision sections) and the architecture sections the spec cites.
5. For each ID, read its row in `docs/traceability.md`: status, implementation, test, evidence.
6. Report: gaps, blocked items, conflicts between spec and code or architecture, and open tasks in `docs/tasks/`.
7. Do not run tests, do not open `.env*` files, do not touch Neon.
