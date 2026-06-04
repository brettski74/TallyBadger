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
- **JSON / form field names (keys):** prefer **`snake_case`** (e.g. `restore_mode`) — aligns with existing API shapes and JS-friendly identifiers.
- **String enumeration values** (not identifiers): prefer **`kebab-case`** (e.g. `erase-reload`) for new or touched restore/import modes — easier to type than `_` or `+`, and visually distinct from keys.
- **Untrusted upload size:** byte limits for client-supplied files (e.g. journal entry attachments) are enforced in **HTTP route handlers** (`src/tallybadger/api/`), not in ledger or other domain services. Domain methods accept bytes the caller has already bounded; server-generated content (e.g. flatbed scan) is not subject to the user-upload cap.

## Inactive objects (`is_active`)

Domain entities that carry an `is_active` flag (today: accounts and parties; the same rule extends to any future table that adopts the column) treat it as a **soft-archive** marker, not a destructive delete. Default contract:

- **New associations are rejected.** Validations on create or on any field change that **introduces a new reference** to a row (e.g. `POST /cheques`, `PATCH /cheques` swapping `credit_account_id`, `PATCH /ledger-settings` setting a default account id) must verify the target is `is_active = TRUE`.
- **Existing associations are preserved.** A row already pointing at a now-inactive entity continues to load, display, list, and edit normally. Editing other fields on that row, or re-affirming the same id in a PATCH body, must **not** re-validate the referenced row's `is_active` state — only an actual id change triggers a fresh eligibility check.
- **UI pickers** shall display a set of options that include all active entities as well as any pre-existing saved value. This means that the user should only be able to select valid values when using the UI.
- **System defaults** (e.g. last-used defaults persisted by a save flow) follow the same "validate-on-change only" rule: a write that introduces a new id validates eligibility; rewriting the same id or leaving the field untouched does not.

Specific flows are free to impose stricter behaviour where it makes product sense (e.g. final clearing or posting against a now-inactive account may warrant a tighter rule, decided per-ticket), but **the default is "inactive blocks new, not existing"**. Do not invent a stricter rule silently — change this section in the same PR.

## Database and migrations

- Ship **SQL migrations** in [`sql/`](sql/) (`NNN_descriptive_name.sql`) in the **same pull request** as code that depends on the new schema.
- Prefer **additive** or **reversible** steps when data is already live.
- Migrations are applied by [`tallybadger.db_migrations`](src/tallybadger/db_migrations.py) in sorted filename order.

## Dev database bootstrap

Local data comes from **snapshot restore**, not a checked-in SQL seed. Two layers:

1. **Foundation configuration (in git):** expanded **configuration** snapshot under **`data/`** (`*.json`, `metadata.json`, generated **`seed_data.deps.mk`**). Canonical archive **`data/seed_data.tar.gz`** is gitignored; regenerate expanded files with **`make -C data regen`** (see **`data/README.md`**). Use **`make -C data upgrade`** when export shape or `format_version` changes.
2. **Full UAT (gitignored):** keep a **complete** snapshot under **`examples/tallybadger-complete-*.tar.gz`** (see **`examples/README.md`**). With the API running, **`make dbclean`** restores the newest match via **`tbload --mode erase-reload`**.
3. Schema changes still ship as **`sql/NNN_*.sql`** migrations; apply with **`make dbempty`** / **`tallybadger-migrate`** when you need a fresh empty schema before restore.

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
- Wherever possible, design and implement tests before implementing application code changes.

## Git, branches, and pull requests

- Build **features and fixes on a branch**; do not land substantive work by committing directly to **`main`** / **`master`**.
- If you are on the default branch, **create and switch to a feature branch** before making changes or commits.
- Branches for new features should be named feature/<issue id>-kebab-case-description
- Branches for bug fixes should be named bugfix/<issue id>-kebab-case-description
- Branches for anything else should be named other/<issue id>-kebab-case-description
- Branches for features, bugfixes or other work always come from main. If you're not on main when starting implementation, notify the user and seek guidance on correcting the issue before doing anything else!
- Merge to the default branch **only through a pull request** that has gone through **human-in-the-loop review** before merge: another person reads and approves (or requests changes) on GitHub when the team has more than one contributor; on a **solo** maintainer repo, use the PR as the deliberate review surface and still avoid merging unreviewed local commits straight to `main`. Prefer **squash merge** so history stays easy to read unless the team agrees otherwise.
- **Link GitHub issues** in the **PR body** with closing keywords when appropriate (`Fixes #42`, `Closes #42`, `Refs #42`) so links survive squash; see [GitHub linking](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue).
- **Features and bugs** are tracked in **GitHub Issues**; PRs should reference them for traceability.

## AI-assisted delivery workflows

Repeatable **phase** procedures live under repo-root **[`workflows/`](workflows/)**. Each phase is a single file **`workflows/<name>.md`**. New workflows are added by **adding that file only**—this section is **not** updated with a list of filenames when you do.

### Shortcut `!wk-<word> #N` (normative)

When the user’s message includes a **core instruction** of the form **`!wk-<word> #N`** (same line may have other text before or after):

1. You **MUST** read the appropriate workflow file for instructions before proceeding with anything!
2. **`N`** — Numeric **GitHub issue** number for **this** repository. Resolve **owner** and **repo** from the workspace (e.g. `git remote` URL) or from explicit user context, then load issue **#N** with GitHub tools (e.g. **`user-github`** MCP **`issue_read`**) **before** planning. Use the issue for acceptance criteria, links, and (when appropriate) comments.
3. **`<word>`** — Must match the stem of **`workflows/<word>.md`** (path is **case-sensitive** on disk; convention is lowercase stems). Read that file **in full** from the workspace and follow it for this ticket. If the file is missing, report that and stop.
4. **Where the syntax lives:** Only **this file** defines `!wk-<word> #N`. Workflow files describe the phase only; they do **not** define chat triggers, so a workflow is discoverable when this shortcut (or an explicit “read `workflows/…`”) pulls it into context.

**Not implied by `!wk-<word> #N` alone:** Merging pull requests, closing issues, or releasing—unless the user **also** asks explicitly or the workflow file clearly assigns that step (e.g. implement may say “open a PR”; **ship** still does **not** put merge on the assistant unless the user separately requests it).

This convention is **agent-agnostic** (not editor-specific). **Do not** duplicate this subsection under [`.cursor/rules/`](.cursor/rules/); the always-on rule only points at **ARCH.md** and **STYLE.md**.

This is important - Merging PRs is only ever done by the human user!!!! 

## PR description hygiene

State **what changed**, **why**, how to **verify** (commands run, screenshots for UI), and **which issue(s)** the PR addresses.

## Error Messages ##

Error messages should be **brief** but **informative**. They should always include the value of **any attribute that contributed to the cause of the error**. When the error involves a named entity (eg. Party, Account, Accrual Plan, Rule Set, etc), the name of that entity must be included in the error message.

## Definition of Done ##

For implementation to be complete:
- All requirements must have been implemented.
- Tests must have been added or updated to adequately test new functionality or fixed bugs (not required when the change set is **markdown-only**; see exception below).
- Make sure you're running all the tests!!!!! I don't know how much more forcefully I can say it, but the section on running the full test suite is part of the definition of done. I'm sick of remining you that this needs to be done as part of implementation.

### Running the full test suite (default — mandatory)

Whenever the change set includes **anything other than Markdown** (any file that is not `*.md`), **all** of the following apply before the work is done:

- **Run every automated test yourself** — do not ask the user to run them. Use `make test` and `make frontend-test` in the Makefile (or equivalent full-suite commands if those targets change).
- **Include integration tests.** `make test` runs the integration suite against Postgres (Docker). If Docker or another dependency is missing, **diagnose and fix it and continue** — do not treat integration tests as optional.
- **No targeted-only runs.** Running a single test file or a subset because the change “looks local” is **not** sufficient.
- **Backend-only or frontend-only changes still require the full suite** — run backend and frontend tests every time.
- **Pre-existing failures do not excuse skipping.** All tests must **pass** before the feature or bugfix is done, even if a failure existed before your branch (fix it or get explicit user direction to defer).

**Markdown-only exception (narrow):** If and only if every file changed in the branch/PR is a **`*.md`** file (e.g. `STYLE.md`, `ARCH.md`, `README.md`, `workflows/*.md`, `docs/*.md`), you **do not** need to run the test suite for that change. The moment **any** non-Markdown file is touched — code, config, SQL, lockfiles, snapshots, CI, etc. — this exception **does not** apply and the full suite is **mandatory**, with no exceptions for “docs-only PR that also tweaks one line of code.”

## Register and list UI

Norms for **filterable, sortable entity registers** in the SPA. The **cheque register** ([`ChequesSection`](frontend/src/components/ChequesSection.tsx)) is the reference implementation; **accrual plans** and **journal entries** should align over time where practical. Pull requests for cheque-register work under epic [#191](https://github.com/brettski74/TallyBadger/issues/191) should **cite this section** in the PR body.

**Aligning existing registers (opportunistic only):** When a PR **already changes** a given register or its modals, bring **that surface** in line with this section as part of the same work—for example, switching cheque re-open from `SquareCheck` to `SquareCheckBig` while implementing cheque-register features. **Do not** use unrelated changes (accounts, journal entries, rule sets, configuration, etc.) to drive wholesale standards alignment on registers you are not touching. If you notice drift elsewhere, note it on a follow-up ticket rather than “fixing icons while you’re here.” Refactoring every existing screen in one go is **out of scope** unless explicitly scoped.

### Page shell

- Wrap the register in a **`section.card`**; use **`journal-card-wide`** when the table needs horizontal room.
- Put the table inside a horizontal-scroll container when columns may overflow (`overflowX: auto` on a wrapper div).
- **Vertical scroll (register list views):** the **app header and main nav**, register **toolbar**, **filter row(s)**, and table **column headers** (`<thead>`) remain visible in the viewport. **Only `<tbody>` data rows** scroll vertically (inline create/edit rows in the accounts table are tbody rows and scroll with the list). Use remaining viewport height below the fixed chrome. Use [`RegisterListCard`](frontend/src/components/RegisterListLayout.tsx), **`RegisterListChrome`**, and **`RegisterListTable`** with the matching classes in [`styles.css`](frontend/src/styles.css) (`.register-list-card`, `.register-list-chrome`, `.register-list-table-area`) rather than per-register one-offs.

### Toolbar

- **Left:** `<h2>` with the section title (e.g. “Cheque register”, “Accrual plans”).
- **Right:** a compact actions cluster (e.g. `cheque-register-toolbar` / `cheque-register-actions` or `journal-list-toolbar` patterns).
- **Refresh** and **New** belong in that right cluster, implemented as [`TableRowIconButton`](frontend/src/components/TableRowIconButton.tsx) with [lucide-react](https://lucide.dev/) icons at **`size={18}`** and **`strokeWidth={2}`**:
  - **Refresh list** — `RefreshCcw`; disable while the list request is in flight; `aria-label` / `title` describe refresh (e.g. “Refresh list”).
  - **New** — `FilePlus2` (prefer this over `FilePlus` on **new** registers; older surfaces may still use `FilePlus` until updated).
- Wire **New** to the keyboard helpers in [`keyboardHints.ts`](frontend/src/lib/keyboardHints.ts): `newEntityAriaLabel`, `newActionTooltip`, `newAriaKeyShortcuts` so **Ctrl+Shift+N** (⌘+Shift+N on macOS) matches the **Keyboard shortcuts** section below—**not** plain Ctrl+N.
- Optional **muted** helper text under the toolbar is fine for domain-specific status rules (see cheque register).

### Filters row

- Place filters **below** the toolbar (e.g. `cheque-register-filters` or `journal-filters-line` on `journal-list-toolbar-with-filters`).
- Include **status** or bucket filters where the entity has lifecycle states (cheque status, accrual settlement bucket, account active visibility, etc.).
- Add **entity-specific** filters (party, account multi-selects, date range, name pattern, etc.) using the same control sizing as journal entries (`journal-filter-slot`, `journal-filter-control`) when reusing that layout.
- **Filter presets** (optional): follow the journal-entries pattern—**Save** icon (`Save` from lucide-react) on `TableRowIconButton` opens save/update preset UI; a **Filter preset** dropdown applies stored definitions. Saving presets is **not** bound to **Ctrl+S** (see **Keyboard shortcuts**).

### Table

- Use a semantic `<table>` with `<thead>` / `<tbody>`.
- **Sortable column headers:** when client-side sort is supported, headers should be clickable controls that toggle sort direction; implement per ticket (not all registers sort yet). Keep sort state visible (e.g. indicator on the active column).
- **Actions** is the **rightmost** column. Row actions live in `table-row-actions` as `TableRowIconButton`s. Use **`e.stopPropagation()`** on action clicks when the row itself is clickable.
- **Standard row icons** (lucide-react, 18px, stroke 2):

| Action | Icon | When |
|--------|------|------|
| Deactivate | `SquareX` | Mark inactive where the entity supports soft-archive (e.g. accounts/parties in draft editors) |
| Delete | `Trash2` | For actions with delete-like semantics like cancelling an accrual plan. |
| Duplicate | `BookCopy` | Duplicate an entity, with intelligent incrementing where appropriate (eg. accrual plans, cheques) |
| Edit | `Pencil` | Editable open/draft rows |
| Reactivate | `SquareCheckBig` | For actions with reactivate type semantics like reactivating an account or re-opening a cheque. |
| View | `Eye` | Read-only detail (cleared/void/settled rows, etc.) |
| Void / cancel | `Ban` | Void cheque or similar destructive cancel on an open row |

- **Entity-specific** actions are allowed when documented in the PR; use consistent icons where possible.
- Existing code may use non-standard icons until that register is next edited; the table above is the **target**, not a mandate to chase every drift in drive-by PRs (see **Aligning existing registers** above).
- Give each button a specific **`aria-label`** (include entity id or name where helpful) and a **`title`** tool tip.

### Empty, loading, and error states

- **List fetch errors:** show above the table as `<p className="error-text">` (or `error` with `role="alert"` where already established on that surface).
- **Loading:** when loading and the in-memory list is still empty, one body row spanning all columns, `className="muted"`, text **Loading…**
- **Empty:** when not loading and the filtered list is empty, same colspan row, text like **No cheques for this filter.** / **No plans for this filter.** — tailor the entity and filter context.
- Do not show an empty message while the first page is still loading.

### Create / edit / view modals

- Use native **`<dialog>`** with shared layout classes (`cheque-dialog`, `cheque-dialog-inner`, `cheque-dialog-header`, `dialog-actions` in [`styles.css`](frontend/src/styles.css)) unless a surface has a strong reason to differ.
- **Size** the dialog so the form fits without vertical scrolling when possible. Scrolling is acceptable for **long embedded lists** (e.g. cheque series preview, accrual entry preview); use `cheque-dialog-preview` where preview content needs extra height.
- **Full-width** controls for free-text fields: summary, description, name, memos (`cheque-form-summary` or equivalent block-level labels).
- **Two- or three-column** layout for compact fields: currency, number, date, picklists—`cheque-form-grid` with `cheque-form-col` columns (see cheque and accrual plan modals).
- **Group related fields** visually (accounts together, dates together, party + accounts on one row, etc.).
- Header: dialog title (`<h2>` with `aria-labelledby` on the dialog) and a **Close** secondary button; footer: **Cancel** + primary **Save** / **Create** in `dialog-actions`. View-only dialogs omit save actions.
- Modal **keyboard shortcuts** (Save, Discard, New, Esc) follow the **Keyboard shortcuts** section; shortcuts apply regardless of focus inside the dialog.

## Keyboard Shortcuts

The following keyboard shortcut standards should be applied throughout the application. Deviations from these norms should be called out during refinement and when presenting an implementation plan. Keyboard shortcuts on modal dialogs should apply regardless of which element currently holds the focus.

### Ctrl+S - Save

For forms that have a **Save** button or any similar function which saves the updates currently pending in the UI, the Ctrl+S key performs the same operation as if this button were pressed. This does not apply to saving search filter presets.

### Ctrl+Shift+D - Discard

For forms that have staged and unsaved changes, discard the changes and revert the form back to original, already saved values. For forms displaying a staged preview of pending changes, discard the preview and return to any prior form without altering values. Pressing Ctrl+Shift+D another time once back at that form would further revert to the previously saved values. This does not apply to search filter parameters.

### Ctrl+Shift+N - New

For forms that have a button to create a new entity of the type being displayed, **Ctrl+Shift+N** (⌘+Shift+N on macOS) should act as if clicking this button (e.g. Create account, New cheque, New accrual plan, Add journal entry). **Do not use plain Ctrl+N** — browsers reserve it for “new window” and the page cannot override it reliably.

### Esc - Cancel/Close

Close any open modal dialog without any additional side effects.

## Consistency checklist (default self-review)

Use this table when preparing a PR; extend it as the repo evolves.

| Area | When it applies | What to update in the same PR |
|------|-----------------|-------------------------------|
| **Database schema / domain model** | Migrations or persisted shapes change | `sql/` migrations; refresh **`examples/tallybadger-complete-*.zip`** when default UAT data must reflect the model; **`make dbclean`** to load it. Update **STYLE.md** for process changes; **ARCH.md** only if boundaries or lifecycle change. |
| **Inactive object handling** | Adding or changing validation around `is_active` on accounts, parties, or any future table with the flag | Apply the default contract from **Inactive objects (`is_active`)** above (new associations rejected, existing preserved, validate on change only); add tests for both the "blocked on change" and "allowed on re-affirm / unrelated edit" cases; update that section in **STYLE.md** if the per-ticket flow needs a stricter rule. |
| **Backup / snapshot / import** | New or changed tables, FKs, or snapshot semantics | Snapshot/import code paths; integration tests; [docs/backup-snapshot-format.md](docs/backup-snapshot-format.md); bump **`format_version`** when required by the format rules. |
| **Public API or stable JSON** | Routes or response shapes consumed by clients | Contract/API tests; docs that promise the shape; **STYLE.md** if testing or contract expectations change. |
| **Architecture vs style / delivery** | Boundaries, trust, integrations, lifecycle vs day-to-day conventions | **ARCH.md** for boundaries/lifecycle; **STYLE.md** for conventions, testing bar, or PR hygiene. **`.cursor/rules/`** only for **wiring** (pointers, tool constraints)—not duplicate policy text. |
| **Feature-level domain docs** | Subtle or cross-cutting behaviour | Extend the relevant file under `docs/`; link from **ARCH.md** when it helps navigation. |
| **Register / list UI** | New or revised filterable entity register | Follow **Register and list UI**; cite that section in PR body when part of cheque-register epic work. |

Never undo user commits or remove them from a branch using git reset or similar commands unless the user explicitly requests you to do so. Assume that the user knows what he/she is doing and if he/she committed something on a branch it's because that is what he/she wanted done.
