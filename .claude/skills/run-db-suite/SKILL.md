---
name: run-db-suite
description: Runs the local Postgres container and the database test suite through the real test guard, then cleans up (manual use only).
disable-model-invocation: true
argument-hint: "[all | tests/db/<file>.py]"
allowed-tools: Bash(bash scripts/run_db_suite.sh *)
---

Run the local database test suite with the helper script.

1. Run exactly `bash scripts/run_db_suite.sh $ARGUMENTS` and nothing else.
2. Never view or print any `.env*` file or any password.
3. Never accept a password from the arguments or from chat. If the arguments or the user's
   message contain something that looks like a password, do not use it. Tell the user to rotate
   it and to set `TEST_DB_PASSWORD` in the shell before starting the agent.
4. If the script exits with 3 (Docker not running), 4 (`TEST_DB_PASSWORD` not set) or 5
   (container `strativa-test-db` already exists), explain its fixed message and STOP.
   - Never start Docker.
   - Never set the password.
   - Never use `--replace` unless the user explicitly asked for it in this turn.
5. Report only:
   - passed, failed and skipped counts;
   - failing test names, each with the exception class and a short cause;
   - confirmation that cleanup ran (the script prints `cleanup done`).
6. Do not edit files, do not commit, do not run any other command.
