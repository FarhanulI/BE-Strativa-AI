# AI Content Studio Project Guidelines

## Source of truth

- Treat [the product architecture](../docs/product-architecture.md) as canonical. Treat [the module map](../docs/modules.md) as the implementation phase order and module inventory.
- When instructions conflict, follow the product architecture and call out the conflict rather than silently introducing a new architectural decision.
- This project is a modular monolith: Next.js, FastAPI, Neon PostgreSQL with pgvector/tsvector, and Redis. Do not introduce microservices, Kafka, or other infrastructure without an explicit request.

## Architecture boundaries

- Every domain module owns its entities, tables, services, API routes, events, jobs, and tests. Integrate modules only through public service interfaces or versioned domain events via the transactional outbox. Never import another module's internals or query its tables.
- Keep Workspace as the collaboration and authorization boundary, and ContentProfile as the strategy boundary. Verify workspace membership and permissions on every request for workspace resources; a workspace ID supplied by a client is not authorization.
- Preserve the product loop: intelligence evidence -> signal synthesis -> strategic signal -> opportunity -> brief -> channel execution -> creation -> publish -> measure -> learn. Do not let raw trends or intelligence events bypass signal synthesis, opportunity, or the required brief.
- Keep human preference separate from audience performance. Preserve user edits and versions; upstream changes must mark downstream work appropriately, never silently discard user-authored content.
- Keep AI provider choice behind the AI Router. Use task-specific context, strict structured-output validation, scoped retrieval, and evidence lineage; do not couple domain logic to a provider or send an entire profile/database as context.
- Store performance as immutable timestamped metric snapshots. Use relational filtering for numeric comparisons before semantic retrieval.

## Change workflow

- Before changing a feature, identify its owning module and whether it is Intelligence, Strategy, Execution, or Learning. Read the relevant architecture sections and module spec first.
- Define or update the module's public contract before wiring consumers. Keep persistence private; publish only the data and events consumers need.
- Include authorization, invariants, failure/retry behavior, idempotency for jobs, and lineage where relevant. Keep long-running AI, embedding, publishing, and ingestion work asynchronous where the architecture calls for it.
- Add focused tests for the changed module and its public contract; add tenant-isolation or end-to-end coverage when a change crosses those boundaries.
- Follow existing repository tooling and conventions. Do not invent build/test commands when none are documented; report checks that could not be run.
- Keep changes minimal and update the architecture or module documentation when behavior or contracts change.

## Standing rules (owner)

- `docs/specs/` are the source of truth. Every module goes spec, implement, verify. Stop for owner review after each step. One agent at a time on a working copy. Commit and push after every step.
- Never run destructive commands (`rm -rf`, `git clean`, force push, dropping databases) without asking the owner.
- Event payload keys never contain the word "token". No prompts, completions or user content in logs, events or error messages.
- Tests run on a local Postgres container by default (`TEST_DB_MODE=local`, `APP_ENV=test`) and on the Neon test branch nightly. Never run tests against dev or production. SQLite is never a substitute.
- Real-provider spend in tests is capped at 20 USD in total. Tests use synthetic text only.
- Never print or log secret values. List variable names only.
- ENV RULE: every variable added to `.env.example` must also be added to `.env.local` in the same change, in the same placeholder form (commented or blank exactly as in `.env.example`), never with a real value. Run `scripts/sync_env_local.py` after editing `.env.example`. Optional variables that must not be exported blank stay commented out.
