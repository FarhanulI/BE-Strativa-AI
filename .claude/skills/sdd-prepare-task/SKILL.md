---
name: sdd-prepare-task
description: Create or update a task file in docs/tasks/ for bounded work, tied to requirement IDs, and propose it as Ready for owner approval.
argument-hint: <module and short goal>
allowed-tools: Read, Grep, Glob, Edit, Write
---

Prepare a task. Follow [docs/sdd.md](../../../docs/sdd.md) sections 4 and 5. The task is not `Ready` until the owner approves it.

1. Run the `sdd-analyze-spec` steps for the module. Stop if no requirement ID applies; a spec change proposal is needed first.
2. Take the next free `T-nnn` from `docs/tasks/README.md`. Copy the template from that file. Every field is mandatory.
3. Fill: module and phase, requirement IDs (valid, existing), spec references, objective, scope, explicit non-goals, dependencies, implementation expectations, required tests, verification requirements (including the environment; Neon only under a separate authorization), acceptance criteria.
4. Set the state to `Proposed`. If a named dependency or authorization is missing, set `Blocked` and name it.
5. Add the task to the index in `docs/tasks/README.md`.
6. write a Commit message of the task citing the task ID. Then stop and ask the owner to approve it as `Ready`.
