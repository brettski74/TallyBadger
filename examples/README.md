# Example snapshots (local UAT)

This directory holds **gitignored** snapshot archives for **full local UAT**, not the version-controlled foundation seed under **`data/`**.

| Location | Export scope | In git? | Typical use |
|----------|--------------|---------|-------------|
| **`examples/tallybadger-complete-*.tar.gz`** | `complete` (configuration + financial) | No | **`make dbclean`** — reset dev DB to a rich UAT dataset |
| **`data/`** expanded JSON + `metadata.json` | `configuration` only | Yes (JSON); archive gitignored | Foundation chart, parties, templates, settings for new installs |

## Complete UAT archives

Place (or export) a **complete** snapshot as:

```text
examples/tallybadger-complete-YYYYMMDD-HHMMSS.tar.gz
```

With the API running and Postgres up:

```bash
make dbclean
```

This runs **`scripts/tbload --mode erase-reload`** on the **newest** matching `examples/tallybadger-complete-*.tar.gz`.

To refresh your local complete archive after schema or data model changes:

```bash
# API running, DB loaded as you want it
scripts/tbsave -o examples/tallybadger-complete-$(date +%Y%m%d-%H%M%S).tar.gz --scope complete
```

Other scopes (`configuration`, `financial`) are useful for ad hoc testing; only **complete** archives are used by **`make dbclean`**.

## Foundation seed vs UAT

- **`data/`** — small, reviewable **configuration** baseline committed to the repo. See **`data/README.md`** for `make regen` / `make upgrade`.
- **`examples/`** — larger **complete** snapshots for day-to-day development; keep them local (or share out-of-band), not in git.

Do not put journal entries, cheques, or other financial tables in committed **`data/`** seed — those belong in complete exports here.
