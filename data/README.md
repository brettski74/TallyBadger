# Configuration seed data

Version-controlled **foundation configuration** for new setups: chart of accounts, parties, import templates, ledger settings, filter presets, and related tables. This is **not** full UAT data (no cheques, journal entries, or accrual history).

| Artifact | In git? | Role |
|----------|---------|------|
| `*.json`, `metadata.json`, `attachments/**` | Yes | Expanded, prettified **format 2.0.0** snapshot members (JSON envelopes + manifest). |
| `seed_data.deps.mk` | Yes | **Generated** Make prerequisites — one `*.json: seed_data.tar.gz` rule per manifest member plus `metadata.json`. **Do not hand-edit.** |
| `seed_data.tar.gz` | No (gitignored) | Canonical **configuration** export; drop a newer archive here, then regen. |

Full UAT snapshots live under **`examples/`** (gitignored `tallybadger-complete-*.tar.gz`) and load via **`make dbclean`** — see **`examples/README.md`**.

## Prerequisites

- **`jq`** on `PATH` (pretty-print only; we do **not** use `jq -S` or other sorting).
- **`scripts/mkmeta`** (repo) — refreshes `member_manifest` SHA-256 digests after prettify.
- For **`upgrade`**: API running, database migrated (`make up` / `make db-migrate`).

## `make regen` (default)

From this directory:

```bash
make regen
# or simply
make
```

When `seed_data.tar.gz` is newer than any output listed in `seed_data.deps.mk` (or outputs are missing), regen will:

1. Extract the archive to a temporary directory.
2. Pretty-print each manifest `*.json` member with **`jq .`** (preserves key and row order).
3. Copy binary `attachments/*` members when present.
4. Write **`metadata.json`** from the archive (preserves **`member_manifest` array order**).
5. Run **`scripts/mkmeta`** on `metadata.json` (digest update only).
6. Rewrite **`seed_data.deps.mk`** from the current manifest.

Regen does **not** run `git add`. If expanded `*.json` files exist that are **not** in the manifest, regen prints **warnings** and suggested `rm -f` lines.

### First-time / bootstrap

If you only have `seed_data.tar.gz` and no `seed_data.deps.mk` yet:

```bash
make regen
```

Commit the resulting `*.json`, `metadata.json`, and `seed_data.deps.mk`. Do **not** commit `seed_data.tar.gz`.

### Initial baseline (maintainers)

1. Start from an empty `data/` tree.
2. With the API running: **`make dbclean`** (loads the newest `examples/tallybadger-complete-*.tar.gz`).
3. **`scripts/tbsave -o data/seed_data.tar.gz --scope configuration`**
4. **`cd data && make regen`**
5. **Manually review** expanded JSON (remove test-only rows, trim parties, etc.) before commit.
6. Commit expanded files + `seed_data.deps.mk`; keep the archive local/gitignored.

## `make upgrade`

Refresh the gitignored archive from the current expanded tree, then regen (API must be running):

```bash
cd data
make upgrade
```

This runs **`tbload -i data/ --mode erase-reload`**, **`tbsave -o seed_data.tar.gz --scope configuration`**, then **`make regen`**.

Use when **`format_version`** or configuration export members change — commit any new/removed `*.json` and the updated **`seed_data.deps.mk`** after review.

## Hygiene

- After dropping a new `seed_data.tar.gz`, run **`make regen`** so JSON, digests, and **`seed_data.deps.mk`** stay aligned.
- Do not hand-edit **`seed_data.deps.mk`**; changes flow through regen or upgrade only.
- Editing expanded JSON without regen can leave digests and Make deps out of sync — run regen after intentional edits or restore from a fresh archive.
