# AI Content Studio Project Guidelines

## Source of truth

- The SDD process, authority hierarchy and task lifecycle are in [docs/sdd.md](../docs/sdd.md). Tasks are in [docs/tasks/](../docs/tasks/README.md).
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
- Never view `.env*` files with any tool; print variable names only. If a secret value is ever shown, report it immediately.
- Run the database suite with /run-db-suite; never set or print the test password.
- Neon runs only in an explicitly authorised, separate task; never in other tasks.

## Spec-Driven Development (SDD) governance

Introduced by the SDD migration (see [decisions.md](../docs/decisions.md), SDD-D-1 to SDD-D-4). These rules add to, and never replace, the rules above. Where they overlap, the stricter rule applies. `CLAUDE.md` keeps importing this file.

### Terminology

- **Module**: an architectural ownership boundary. The module map is [docs/modules.md](../docs/modules.md), which documents 37 modules.
- **Phase**: a delivery grouping and implementation order. The module map has 10 phases (0 to 9). A phase is not a module.
- **Task**: an independently scoped unit of work within a module.
- **Milestone**: an owner-reviewed stage of the SDD migration or of project delivery.

### Rules

1. Every implementation task references its approved module specification and the relevant AC/INV IDs.
2. Every task states its expected implementation and verification evidence before work starts.
3. Commit messages reference the relevant requirement, decision or task ID where applicable.
4. If implementation and specification conflict, write a change proposal. Never silently modify an approved spec.
5. A spec is Draft, Approved or Superseded. An Approved spec identifies its revision and approval date.
6. A requirement is Specified, Implemented, Verified, Gap or Blocked, as defined in [docs/traceability.md](../docs/traceability.md).
7. Verified requires dated test execution evidence recorded in `docs/traceability.md` or an associated verification report. A closed phase or an existing test file is not evidence.
8. Task lists and verification reports are subject to milestone-level owner review.
9. The security, environment, database and repository safety rules above remain authoritative, including the rule that Neon runs only in an explicitly authorised, separate task.
10. Decisions made for SDD are recorded in [docs/decisions.md](../docs/decisions.md) under the `SDD-D-n` namespace. Existing `D-n` decisions are never renumbered or redefined there.

### Agent workflow rules (SDD)

Defined in [docs/sdd.md](../docs/sdd.md). They add to the rules above and never relax a safety rule.

11. Before implementing, read the module map entry and the module spec, identify the applicable requirement IDs (`<MODULE>-INV-n`, `<MODULE>-AC-n`; AI Platform `INV-n`, `AC-n`), and check [docs/decisions.md](../docs/decisions.md) and the architecture boundaries.
12. Substantial implementation needs a `Ready` task in [docs/tasks/](../docs/tasks/README.md) that names the requirement IDs. Create or update the task first. Work only inside the task scope; if the scope must change, stop and update the task.
13. Add or update tests for each applicable acceptance criterion, and update [docs/traceability.md](../docs/traceability.md) after implementation. Cite the task and requirement IDs in commit messages.
14. Record actual verification evidence (date, command or skill, environment, counts). Never claim verification without execution evidence. Local PostgreSQL never verifies a requirement that names Neon.
15. Never reuse or renumber a requirement ID. Never silently change an approved spec; write a change proposal (rule 4). Record new decisions as `SDD-D-n` and never override an existing decision.
16. The database suite runs only through `/run-db-suite`. Do not create commands or scripts that bypass the database, Neon, secret or environment rules.
17. Stop and report when owner approval or external authorization is required (Neon, spec approval, a new decision, scope change, missing spec). A `Blocked` task stays `Blocked`; do not work around it.
