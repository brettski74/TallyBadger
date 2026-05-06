# TallyBadger coding style and engineering standards

This file is the **single human- and agent-visible source of truth** for how we write code, test it, and ship it. **Architecture and subsystem boundaries** live in **[ARCH.md](ARCH.md)**. Cursor and other assistants should read **both** before planning or implementing substantive work.

## Languages and tooling

- **Backend:** Python **3.11+** (see `requires-python` in [`pyproject.toml`](pyproject.toml)). Layout: package under [`src/tallybadger/`](src/tallybadger/).
- **Frontend:** TypeScript, React, Vite; tests via **Vitest** and Testing Library (`frontend/`).
- **Formatting / linting:** There is no repo-wide Ruff/ESLint config yet; **match the style of surrounding code** (imports, naming, typing). When adding shared lint/format config, document it here in the same PR.

## Money and numeric correctness

- Use **`Decimal`** or **integer minor units** for currency and amounts in **new** code—never `float` for money.

## API contracts and configuration

- Treat **published HTTP routes** and **stable JSON response shapes** as contracts: change them together with **tests** and any **user-facing or integration documentation** that promises that shape.
- **Secrets:** never commit credentials. Use environment variables (prefix **`TALLYBADGER_`** where applicable, see [`Settings`](src/tallybadger/core/config.py)) or your deployment’s secret store.

## Database and migrations

- Ship **SQL migrations** in [`sql/`](sql/) (`NNN_descriptive_name.sql`) in the **same pull request** as code that depends on the new schema.
- Prefer **additive** or **reversible** steps when data is already live.
- Migrations are applied by [`tallybadger.db_migrations`](src/tallybadger/db_migrations.py) in sorted filename order.

## Dev database and `export-dev-seed`

When the **persisted model or seed-relevant data** changes, keep local bootstrap truthful:

1. Recreate/migrate as needed (e.g. `make dbclean` for a clean local DB with migrations + [`sql/dev_seed.sql`](sql/dev_seed.sql)).
2. After loading representative data, run **`make export-dev-seed`** and commit the updated **`sql/dev_seed.sql`** when the team should see the new shape by default.

This pairs with schema work so portable paths (clone → migrate → seed) stay reliable.

## Backup, snapshot, and import

- Snapshot **layout and semantics** are defined in **[docs/backup-snapshot-format.md](docs/backup-snapshot-format.md)** (`format_version`, `schema_version`, export modes, member manifest).
- Pull requests that change **included tables**, **foreign keys**, **import validation**, or **restore behaviour** should update:
  - implementation under [`src/tallybadger/backup/`](src/tallybadger/backup/) and routes as needed;
  - **integration tests** covering export/import;
  - the **format doc** when operators or integrators need new facts.
- Bump **`format_version`** when a change **requires** new consumer logic or breaks prior archives (per the format doc’s version rules).
- Restore should support the current format_version and also the prior 3 format_versions to allow recovery from older backups if necessary. Breaking data model changes (eg. non-nullable fields added to existing tables) will need clear migration rules specified so that this requirement can be fulfilled.

## Testing

- Every **feature** or **bug fix** includes **at least one new automated test**; add more when behaviour warrants it.
- **Backend** ([`src/tallybadger/`](src/tallybadger/), [`tests/`](tests/)): use **pytest** (`TestClient` for HTTP, plain functions for domain). Use the **`integration`** marker when a live **PostgreSQL** instance is required (`make test` / `make test-integration`).
- **Frontend:** non-trivial UI changes should include **automated tests** (Vitest; add e2e/smoke when that stack exists). Until UI surface is large, API tests may carry more weight—see [ARCH.md](ARCH.md).
- **Design for testability:** keep ledger and domain rules testable **without HTTP** where practical; inject config, DB, or session dependencies; avoid hidden globals that block assertions.

## Git, branches, and pull requests

- Build **features and fixes on a branch**; do not land substantive work by committing directly to **`main`** / **`master`**.
- If you are on the default branch, **create and switch to a feature branch** before making changes or commits.
- Merge to the default branch **only through a pull request** that has gone through **human-in-the-loop review** before merge: another person reads and approves (or requests changes) on GitHub when the team has more than one contributor; on a **solo** maintainer repo, use the PR as the deliberate review surface and still avoid merging unreviewed local commits straight to `main`. Prefer **squash merge** so history stays easy to read unless the team agrees otherwise.
- **Link GitHub issues** in the **PR body** with closing keywords when appropriate (`Fixes #42`, `Closes #42`, `Refs #42`) so links survive squash; see [GitHub linking](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue).
- **Features and bugs** are tracked in **GitHub Issues**; PRs should reference them for traceability.

## AI-assisted delivery workflows

Repeatable **phase** procedures live under repo-root **[`workflows/`](workflows/)**:

| File | Phase |
|------|--------|
| [`workflows/refine.md`](workflows/refine.md) | Requirements refinement (feature issues) |
| [`workflows/implement.md`](workflows/implement.md) | Implementation, verification, and PR |
| [`workflows/uat.md`](workflows/uat.md) | User acceptance testing and fix loop |

**Shortcut vocabulary (normative):** When the user’s **core instruction** is one of the following, `N` must be the GitHub issue number (for example `84`). Any assistant that has read this file **must** treat the instruction as: **read** the listed workflow file and **execute** that procedure for issue `#N` (incorporating that file into the effective task prompt).

| Shortcut | Workflow |
|----------|----------|
| `!refine #N` | [`workflows/refine.md`](workflows/refine.md) |
| `!implement #N` | [`workflows/implement.md`](workflows/implement.md) |
| `!uat #N` | [`workflows/uat.md`](workflows/uat.md) |

This mapping is **agent-agnostic** (not editor-specific). **Do not** duplicate these shortcut definitions under [`.cursor/rules/`](.cursor/rules/); the existing rule there only points agents at **ARCH.md** and **STYLE.md**—that remains the single Cursor-specific hook.

## PR description hygiene

State **what changed**, **why**, how to **verify** (commands run, screenshots for UI), and **which issue(s)** the PR addresses.

## Consistency checklist (default self-review)

Use this table when preparing a PR; extend it as the repo evolves.

| Area | When it applies | What to update in the same PR |
|------|-----------------|-------------------------------|
| **Database schema / domain model** | Migrations or persisted shapes change | `make dbclean` (or equivalent); `sql/` migrations; run **`make export-dev-seed`** and commit `sql/dev_seed.sql` when default seed data must reflect the model. Update **STYLE.md** for process changes; **ARCH.md** only if boundaries or lifecycle change. |
| **Backup / snapshot / import** | New or changed tables, FKs, or snapshot semantics | Snapshot/import code paths; integration tests; [docs/backup-snapshot-format.md](docs/backup-snapshot-format.md); bump **`format_version`** when required by the format rules. |
| **Public API or stable JSON** | Routes or response shapes consumed by clients | Contract/API tests; docs that promise the shape; **STYLE.md** if testing or contract expectations change. |
| **Architecture vs style / delivery** | Boundaries, trust, integrations, lifecycle vs day-to-day conventions | **ARCH.md** for boundaries/lifecycle; **STYLE.md** for conventions, testing bar, or PR hygiene. **`.cursor/rules/`** only for **wiring** (pointers, tool constraints)—not duplicate policy text. |
| **Feature-level domain docs** | Subtle or cross-cutting behaviour | Extend the relevant file under `docs/`; link from **ARCH.md** when it helps navigation. |
