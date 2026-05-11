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

## Inactive objects (`is_active`)

Domain entities that carry an `is_active` flag (today: accounts and parties; the same rule extends to any future table that adopts the column) treat it as a **soft-archive** marker, not a destructive delete. Default contract:

- **New associations are rejected.** Validations on create or on any field change that **introduces a new reference** to a row (e.g. `POST /cheques`, `PATCH /cheques` swapping `credit_account_id`, `PATCH /ledger-settings` setting a default account id) must verify the target is `is_active = TRUE`.
- **Existing associations are preserved.** A row already pointing at a now-inactive entity continues to load, display, list, and edit normally. Editing other fields on that row, or re-affirming the same id in a PATCH body, must **not** re-validate the referenced row's `is_active` state — only an actual id change triggers a fresh eligibility check.
- **UI pickers** filter to active options for new associations, but should keep an already-stored inactive value visible (annotated if helpful) when editing the row so the operator can leave it in place or replace it deliberately.
- **System defaults** (e.g. last-used defaults persisted by a save flow) follow the same "validate-on-change only" rule: a write that introduces a new id validates eligibility; rewriting the same id or leaving the field untouched does not.

Specific flows are free to impose stricter behaviour where it makes product sense (e.g. final clearing or posting against a now-inactive account may warrant a tighter rule, decided per-ticket), but **the default is "inactive blocks new, not existing"**. Do not invent a stricter rule silently — change this section in the same PR.

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

Repeatable **phase** procedures live under repo-root **[`workflows/`](workflows/)**. Each phase is a single file **`workflows/<name>.md`**. New workflows are added by **adding that file only**—this section is **not** updated with a list of filenames when you do.

### Shortcut `!wk-<word> #N` (normative)

When the user’s message includes a **core instruction** of the form **`!wk-<word> #N`** (same line may have other text before or after):

1. **`N`** — Numeric **GitHub issue** number for **this** repository. Resolve **owner** and **repo** from the workspace (e.g. `git remote` URL) or from explicit user context, then load issue **#N** with GitHub tools (e.g. **`user-github`** MCP **`issue_read`**) **before** planning. Use the issue for acceptance criteria, links, and (when appropriate) comments.
2. **`<word>`** — Must match the stem of **`workflows/<word>.md`** (path is **case-sensitive** on disk; convention is lowercase stems). Read that file **in full** from the workspace and follow it for this ticket. If the file is missing, report that and stop.
3. **Where the syntax lives:** Only **this file** defines `!wk-<word> #N`. Workflow files describe the phase only; they do **not** define chat triggers, so a workflow is discoverable when this shortcut (or an explicit “read `workflows/…`”) pulls it into context.

**Not implied by `!wk-<word> #N` alone:** Merging pull requests, closing issues, or releasing—unless the user **also** asks explicitly or the workflow file clearly assigns that step (e.g. implement may say “open a PR”; **ship** still does **not** put merge on the assistant unless the user separately requests it).

This convention is **agent-agnostic** (not editor-specific). **Do not** duplicate this subsection under [`.cursor/rules/`](.cursor/rules/); the always-on rule only points at **ARCH.md** and **STYLE.md**.

This is important - Merging PRs is only ever done by the human user!!!! 

## PR description hygiene

State **what changed**, **why**, how to **verify** (commands run, screenshots for UI), and **which issue(s)** the PR addresses.

## Consistency checklist (default self-review)

Use this table when preparing a PR; extend it as the repo evolves.

| Area | When it applies | What to update in the same PR |
|------|-----------------|-------------------------------|
| **Database schema / domain model** | Migrations or persisted shapes change | `make dbclean` (or equivalent); `sql/` migrations; run **`make export-dev-seed`** and commit `sql/dev_seed.sql` when default seed data must reflect the model. Update **STYLE.md** for process changes; **ARCH.md** only if boundaries or lifecycle change. |
| **Inactive object handling** | Adding or changing validation around `is_active` on accounts, parties, or any future table with the flag | Apply the default contract from **Inactive objects (`is_active`)** above (new associations rejected, existing preserved, validate on change only); add tests for both the "blocked on change" and "allowed on re-affirm / unrelated edit" cases; update that section in **STYLE.md** if the per-ticket flow needs a stricter rule. |
| **Backup / snapshot / import** | New or changed tables, FKs, or snapshot semantics | Snapshot/import code paths; integration tests; [docs/backup-snapshot-format.md](docs/backup-snapshot-format.md); bump **`format_version`** when required by the format rules. |
| **Public API or stable JSON** | Routes or response shapes consumed by clients | Contract/API tests; docs that promise the shape; **STYLE.md** if testing or contract expectations change. |
| **Architecture vs style / delivery** | Boundaries, trust, integrations, lifecycle vs day-to-day conventions | **ARCH.md** for boundaries/lifecycle; **STYLE.md** for conventions, testing bar, or PR hygiene. **`.cursor/rules/`** only for **wiring** (pointers, tool constraints)—not duplicate policy text. |
| **Feature-level domain docs** | Subtle or cross-cutting behaviour | Extend the relevant file under `docs/`; link from **ARCH.md** when it helps navigation. |
