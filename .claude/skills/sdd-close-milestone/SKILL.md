---
name: sdd-close-milestone
description: Validate documentation consistency for a milestone with read-only checks, produce the close-out report, and stop for owner review.
argument-hint: <milestone name>
allowed-tools: Read, Grep, Glob, Bash(git status:*), Bash(git log:*), Bash(git diff:*)
---

Close out a milestone. Follow [docs/sdd.md](../../../docs/sdd.md). Inspection only; run no tests and no application code.

1. `git status`: nothing unrelated is uncommitted. Review the diff of every commit in the milestone.
2. Requirement IDs: no duplicates inside a spec; no ID reused or renumbered; AI Platform `INV-n`/`AC-n`/`D-n` unchanged.
3. Traceability: every row points to an existing spec requirement; every spec requirement has a row; no `Verified` without a dated evidence record; no row exceeds its evidence.
4. Tasks: every task cites valid requirement IDs or names its dependency; blocked tasks name the blocker; none is marked complete without evidence and owner review.
5. Links and cross-references in `docs/` resolve. `modules.md` still lists 37 modules in 10 phases. `CLAUDE.md` still imports `.github/copilot-instructions.md`. Safety rules intact.
6. Report: changed files, counts (requirements, mapped, verified, gap, blocked), tasks, unresolved owner decisions, what was not executed and why, git outcome (commits, push status, HEAD).
7. Do not start the next milestone. Stop for owner review.
