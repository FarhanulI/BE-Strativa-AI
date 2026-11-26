---
name: sdd-kickoff-phase
description: Check whether a delivery phase is ready to start by reading its modules, specs, traceability, open tasks and blockers, and report what must exist first. Read-only.
argument-hint: <phase number, for example 3>
allowed-tools: Read, Grep, Glob, Bash(git status:*), Bash(git log:*)
---

Prepare a phase kickoff report. Follow [docs/sdd.md](../../../docs/sdd.md). Do not edit files, run no tests and no application code, do not open `.env*` files, do not touch Neon.

1. In `docs/modules.md`, list the modules of the phase and the phases they depend on. A phase is a build order, not a module.
2. For each module, check that `docs/specs/<feature>/spec.md` exists. Report its status, revision and approval exactly as written (`Not stated` stays `Not stated`). A module without an approved spec cannot be tasked (rule 1, rule 12).
3. For each earlier phase it depends on, read its rows in `docs/traceability.md`: counts by status and any `Gap` or `Blocked` row. Do not call a phase complete because it is closed (traceability rule 10).
4. List open tasks in `docs/tasks/README.md` that touch the phase or its dependencies, with state and blocker. List open questions (`docs/open-questions.md`, AI Platform section 19) and ADRs that apply.
5. Check the safety prerequisites that the phase needs (database mode, Redis, provider keys, privacy review D-27, spend cap) and state which are missing.
6. Report: modules and spec state, dependency evidence gaps, blockers, owner decisions needed, and a proposed task list (titles, requirement IDs, order). Propose; do not create task files (that is `sdd-prepare-task`).
7. Stop for owner review. Do not start the phase.
