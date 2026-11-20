# T-017: Add and pin the LiteLLM dependency

- **Module and phase:** ai_platform, Phase 2
- **State:** Implemented (stops 1 to 3 done 2026-11-20 with `litellm==1.109.1`; DB suite 200 passed; awaiting owner result review)
- **Requirement IDs:** INV-1 and AC-1 (provider SDK imports confined to `app/ai_platform/`). This task is a prerequisite for the adapter and does not change their status.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) section 1 (provider abstraction through LiteLLM), INV-1, AC-1, D-21, D-22, section 20.4; [conformance report](../architecture/conformance-report.md) F-4
- **Dependencies:** T-013 (CI) so that the lock change is tested on a clean install. Owner approval at each stop below. **Always-stop gate: this task never proceeds from one stop to the next without the owner.**

## Objective
Declare LiteLLM as a dependency with an exact version and a reproducible lock, with no application code using it yet.

## Scope
**Stop 1, proposal.** Present the candidate exact version with: release date and age, license, published security advisories at that date, the full list of new transitive packages (names and versions) from a dry-run resolution, and the impact on install size. Run nothing that changes the repository.
**Stop 2, change.** After approval: add `litellm==<exact version>` to `pyproject.toml`, regenerate `uv.lock`, commit both. Show the lock diff (added and changed packages) to the owner.
**Stop 3, check.** Run the DB-free suite, the architecture tests (INV-1 and AC-1 boundary test, provider identifier tests) and a clean `uv sync --locked`, and report.

## Non-goals
Any `import litellm` in `app/`. The provider adapter, a real provider call, key handling (D-22), any catalog data (T-018). Upgrading other dependencies. Verifying the Perplexity decoding questions listed in spec 20.4; those belong to the adapter task and need the installed version this task provides.

## Implementation expectations
The version is chosen only from information fetched in the session (package index and release notes), not from memory. No `uv add` or lock command runs before stop 2 is approved. The owner decides the version.

## Required tests
Existing architecture tests unchanged and passing. `uv sync --locked` succeeds from a clean environment.

## Verification requirements
Command lines, exit codes and counts for stop 3, with the dependency evidence from stop 1 attached to the record (T-014 format). Items not run are `NOT RUN`.

## Acceptance criteria
- `pyproject.toml` pins the exact version and `uv.lock` matches.
- No file under `app/` imports `litellm`.
- The architecture tests pass; the lock diff was reviewed by the owner.

## Stop 1 proposal (2026-11-20), nothing in the repository was changed
Sources fetched in the session: PyPI JSON (`https://pypi.org/pypi/litellm/json`, per-package version JSON), OSV (`https://api.osv.dev/v1/query`, ecosystem PyPI), and the GitHub release pages for v1.109.1, v1.109.2, v1.109.3, v1.110.1, v1.110.2 plus the releases list (read through a fetch subagent; the list page was truncated, so its summary lines are model-extracted and marked below). Resolution: `uv lock --dry-run --python 3.12` on scratch copies of `pyproject.toml` and `uv.lock` with `litellm==<version>` added (exit 0 for each of 1.108.1, 1.108.7, 1.108.13 and 1.109.1); the repository was not touched.

**Package facts.** Latest is 1.110.2 (2026-11-20). License MIT (`license_expression`). Requires Python `>=3.10,<3.16`. About 968 releases; wheels are `cp310-abi3`, so Python 3.12 is covered; the Windows wheel of 1.109.1 is 42.0 MB. No release of the last 75 days is yanked.

**Candidate versions** (age counted to 2026-11-20):
| Version | Released | Age | Note |
| --- | --- | --- | --- |
| 1.109.1 | 2026-11-12 | 8 days | Newest release that is at least 7 days old. Release notes read directly: 2 PRs, the one "action required" item concerns proxy request credentials, not SDK functions. **Proposed.** |
| 1.108.7 | 2026-11-12 | 8 days | Older minor line (1.108; the releases list marks 1.108.12 as "LTS", a model-extracted summary line that was not confirmed on a tag page). Fallback. |
| 1.109.2 / 1.109.3 / 1.110.1 / 1.110.2 / 1.108.13 | 2026-11-19 to 2026-11-20 | 0 to 1 day | Not proposed: not yet in use for a week. 1.109.2 adds Gemini batches and a Perplexity cached-token billing fix (not needed: cost comes from the catalog, not LiteLLM, D-22 and spec section 8). |

**Security.** OSV returned 85 records, 45 distinct advisories. None lists 1.108.1 to 1.110.2 (29 versions checked, including every candidate above) as affected. The newest advisory was published 2026-10-27. Two records matter for supply-chain risk: `PYSEC-2026-2` and `MAL-2026-2144` (2026-03-24): versions 1.82.7 and 1.82.8 contained credential-harvesting malware. They are far below every candidate. The advisory titles I read are about proxy-server features (SSO, admin keys, MCP, guardrails); we would use only the library, but I did not audit each advisory for library impact. The release notes I read mention no security fix, CVE, GHSA, revoked release or SDK breaking change. Same-day patch releases across all lines on 2026-11-19 and 2026-11-20 are not explained on the pages I read; advisories for those days may not be published yet. That is the reason to avoid the newest releases.

**Transitive packages (identical set for all four versions): 44 added, 1 changed.** Changed: `certifi` 2026.7.22 to 2026.10.23. Added (versions from the 1.109.1 resolution): aiohappyeyeballs 2.7.1, aiohttp 3.14.5, aiosignal 1.4.0, attrs 26.1.0, boto3 1.44.7, botocore 1.44.7, charset-normalizer 3.5.2, fastuuid 0.14.0, filelock 4.2.12, frozenlist 1.8.0, fsspec 2026.9.0, h2 4.4.1, hf-xet 1.8.0, hpack 4.2.0, httpcore2 2.16.2, httpx2 2.16.2, httpx2-jsfetch 1.0, huggingface-hub 1.33.0, hyperframe 6.1.0, importlib-metadata 8.9.0, jinja2 3.1.6, jiter 0.19.0, jmespath 1.1.0, jsonschema 4.26.0, jsonschema-specifications 2025.9.1, litellm, multidict 7.2.1, openai 3.57.0, propcache 0.5.4, python-dateutil 2.9.0.post0, referencing 0.37.0, regex 2026.11.19, requests 2.34.2, rpds-py 2026.9.1, s3transfer 0.19.3, six 1.17.0, sniffio 1.3.1, tiktoken 0.14.0, tokenizers 0.23.3, tqdm 4.70.1, truststore 0.10.5, urllib3 2.8.0, yarl 1.25.1, zipp 4.1.2. Only `filelock` differs by LiteLLM version (3.32.7 with 1.108.1, 4.2.12 with 1.108.13 and 1.109.1). Of note: LiteLLM pulls the `openai` SDK and `boto3` / `botocore` transitively. Spec D-4 says `ai_platform` does not use OpenAI; the package is installed as LiteLLM's dependency only, and INV-1 and AC-1 (no import outside `app/ai_platform/`) still apply to it. Licenses of the added packages (PyPI metadata): MIT, Apache-2.0, BSD-3-Clause, MPL-2.0 AND MIT (tqdm), PSF-2.0, and a few unlabeled; I did not review them individually.

**Install size.** Download size of the 44 added packages plus LiteLLM (Windows or pure wheels): about 73.6 MB, of which litellm is 42.0 MB and botocore 16.7 MB. Installed (unpacked) size was not measured.

**Not done at stop 1 (NOT RUN):** license review of each transitive package; a read of the advisories for library impact; release notes for versions other than those listed; any `uv add`, `uv lock` that writes, or edit of `pyproject.toml` or `uv.lock`.

**Decision requested (stop 2 approval):** the exact version. Proposed `litellm==1.109.1`; fallback `litellm==1.108.7`.

## Stop 2 record (2026-11-20)
The owner approved `litellm==1.109.1` (proposed version, not the fallback).
- Edit: `pyproject.toml` gains one line, `"litellm==1.109.1",`, in `[project] dependencies` (alphabetical position after `fastapi`). No other line changed.
- Command: `uv lock --python 3.12`. Exit code 0. "Resolved 96 packages in 93ms".
- Lock diff (`git diff --stat`): `pyproject.toml` 1 insertion; `uv.lock` 1593 insertions, 3 deletions. The 3 deleted lines are the old `certifi` entry (version, sdist, wheel). Added packages: 44, identical to the stop 1 dry-run: aiohappyeyeballs, aiohttp, aiosignal, attrs, boto3, botocore, charset-normalizer, fastuuid, filelock, frozenlist, fsspec, h2, hf-xet, hpack, httpcore2, httpx2, httpx2-jsfetch, huggingface-hub, hyperframe, importlib-metadata, jinja2, jiter, jmespath, jsonschema, jsonschema-specifications, litellm 1.109.1, multidict, openai 3.57.0, propcache, python-dateutil, referencing, regex, requests, rpds-py, s3transfer, six, sniffio, tiktoken, tokenizers, tqdm, truststore, urllib3, yarl, zipp. Changed: `certifi` v2026.7.22 to v2026.10.23. No other existing package changed version.
- The lock's project entry carries `{ name = "litellm", specifier = "==1.109.1" }`.
- `uv sync` was not run: the local virtual environment is unchanged. Stop 3 runs the clean-install check.

## Stop 3 record (2026-11-20, owner approved)
All commands ran in a fresh scratch environment (`UV_PROJECT_ENVIRONMENT` in the session scratchpad, directory did not exist beforehand), so the working `.venv` was not used. Local Windows, Python 3.12.14, `uv 0.12.5`. Commit under test: `uv.lock` and `pyproject.toml` as committed in stop 2.
| # | Command | Exit | Result |
| --- | --- | --- | --- |
| 1 | `uv sync --locked --python 3.12` | 0 | installed from the lock; `--locked` means the lock was not modified |
| 2 | `uv run --locked --no-sync --python 3.12 python -c "importlib.metadata.version(...)"` | 0 | litellm 1.109.1, openai 3.57.0, certifi 2026.10.23 (metadata only; litellm was not imported) |
| 3 | `env -u TEST_REDIS_URL uv run --locked --no-sync --python 3.12 python scripts/check.py` | 0 | ruff clean; mypy clean (36 files); pytest `-m "not db"`: 1709 passed, 4 skipped, 0 failed, 200 deselected. Same counts as the T-016 baseline. The 4 skipped are the Redis-only tests (`TEST_REDIS_URL` unset for this command). |
| 4 | `env -u TEST_REDIS_URL uv run --locked --no-sync --python 3.12 python -m pytest tests/unit/architecture -q` | 0 | 111 passed, 0 failed. Includes `test_ai_platform_litellm_boundary.py` (INV-1 and AC-1) and `test_ai_platform_provider_identifiers.py`. |
| 5 | `uv pip check` against the scratch environment | 0 | "Checked 94 packages", all installed packages are compatible |
| 6 | `uv lock --check --python 3.12` | 0 | "Resolved 96 packages"; lock matches `pyproject.toml` |
| 7 | grep for `import litellm` or `from litellm` under `app/` | n/a | 0 matches |

**Acceptance criteria:** `pyproject.toml` pins `litellm==1.109.1` and `uv.lock` matches (rows 1, 6); no file under `app/` imports `litellm` (row 7); the architecture tests pass (row 4); the lock diff was shown to the owner at stop 2 and the owner approved stop 3.

**Requirement status:** INV-1 and AC-1 are unchanged by this task (it is their prerequisite). No row moved.

**Local database suite, 2026-11-20 (owner ran `/run-db-suite all`):** `bash scripts/run_db_suite.sh all`, exit 0, 200 passed, 0 failed, 1713 deselected, `cleanup done`. Local Postgres container and local Redis (`TEST_REDIS_URL` set, Redis running), `TEST_DB_MODE=local`. The run's `uv run` synced the working `.venv` to the new lock first ("Uninstalled 2 packages, Installed 45 packages": litellm and its 43 new dependencies plus the updated `certifi`, as in the lock diff). Same count as the T-016 after-run (200).

**NOT RUN:** CI (T-013 deferred); the independent audit; a license review of the transitive packages; a real LiteLLM import or provider call (non-goals).

## Evidence
Stops 1, 2 and 3 are recorded above.

## Review and approval
All three stops approved and done on 2026-11-20. Result review requested (gate always: dependency). Independent audit (sdd.md section 11): NOT RUN. **Gate: always** (dependency). The owner must approve each of the three stops.
