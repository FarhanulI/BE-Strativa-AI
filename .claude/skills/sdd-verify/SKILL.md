---
name: sdd-verify
description: Record real execution evidence for a task's requirements and update traceability statuses honestly.
argument-hint: <task ID>
---

Record verification evidence. Follow [docs/sdd.md](../../../docs/sdd.md) section 6 and the status rules in `docs/traceability.md`.

1. Open the task and list its required tests and verification requirements.
2. Run only what is permitted:
   - DB-free tests with the repository's documented command.
   - The database suite only through `/run-db-suite`. It stays authoritative; do not set or print a password, do not start Docker, do not run any DB command directly.
   - Never run anything on Neon. A Neon criterion needs a separate explicitly authorized task. If the task requires it, leave the row `Blocked` and stop.
   - Never open `.env*` files.
3. Record the actual result: date, command or skill, environment (local container or other), passed/failed/skipped counts, failing test names. Put it in the task's Evidence section and in the `Evidence` column of `docs/traceability.md`.
4. Set each row's status:
   - `Verified` only if a dated run covers the requirement's scope and environment.
   - `Implemented` if code exists but evidence is missing or does not match.
   - `Gap` for failures or missing tests; `Blocked` with the named blocker otherwise.
5. A test file, a test name or an agent's claim is not evidence. Do not infer a pass.
6. Set the task `Verified` only if every required requirement is `Verified`. Otherwise leave it `Implemented` and list what is missing. Commit and push.
