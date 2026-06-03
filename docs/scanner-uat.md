# Scanner UAT (flatbed, host API)

Slice A ([#258](https://github.com/brettski74/TallyBadger/issues/258)) runs scanning on the **API host**, not in the browser. When a **scanner device URI** is saved in Configuration (or set via `TALLYBADGER_SCANNER_DEVICE_URI`), the API uses the **HPLIP/SANE** backend automatically. With no device URI configured, scans use the **stub** backend (instant 1×1 JPEG for automated tests). Set `TALLYBADGER_SCAN_BACKEND=stub` to force stub even when a URI is configured.

## Prerequisites

- PostgreSQL up (`make db-up` or `docker compose up -d db`)
- API on the **host** (`.venv` + `tbad up` / README quick start)
- `scanimage` on `PATH` (`sane-utils` / HPLIP packages)
- Flatbed-capable device visible to SANE

List devices:

```bash
scanimage -L
```

Example device (operator UAT):

```text
hpaio:/net/HP_LaserJet_MFP_M227-M231?ip=192.168.1.1
```

## Configuration

1. **Configuration** tab → **Scanner (flatbed)** → set **Scanner device URI** and save, or use env override:
   - `TALLYBADGER_SCANNER_DEVICE_URI=hpaio:/net/HP_LaserJet_MFP_M227-M231?ip=192.168.1.1`
2. Restart the API after **env-only** changes. Saving the URI in Configuration does not require a restart.

Optional ledger settings: `max_scanned_pages` (default 50, v1 uses one page), `scan_dpi` (default 300). Colour mode is greyscale only in v1.

## Deviations from parent #213 spec (slice A)

| Original | Implemented |
|----------|-------------|
| JPEG quality 80 | **scanimage default** (~75); no quality knob — SANE does not expose reliable per-quality control without post-processing |
| Configurable page size | **Fixed US Letter** scan area: 215.9 × 279.4 mm |
| `scan_jpeg_quality` on `ledger_settings` | **Omitted** |

## Smoke test (scanimage directly)

Geometry uses SANE **-l / -t / -x / -y** (not `--page-width`). Letter width 215.9mm, height 279.4mm:

```bash
scanimage -d 'hpaio:/net/HP_LaserJet_MFP_M227-M231?ip=192.168.1.1' \
  --source Flatbed --mode Gray --resolution 300 \
  -l 0 -t 0 -x 215.9mm -y 279.4mm \
  --format=jpeg --output /tmp/tb-scan-smoke.jpg
file /tmp/tb-scan-smoke.jpg
```

## Smoke test (CLI)

With the API running and env set as above:

```bash
curl -sS -o /tmp/tb-scan-test.jpg -w '%{http_code}\n' -X POST http://127.0.0.1:8080/scanner/flatbed
file /tmp/tb-scan-test.jpg
```

Expect HTTP `200` and `JPEG image data`.

## Smoke test (UI)

1. Open any journal entry (party on lines is **not** required for attach-to-JE).
2. **Attachments** → **Scan** (FileScan icon).
3. Enter summary → **Scan and attach**.
4. Confirm JPEG appears in the list (view / download). Filename: `{entry_date_yyyymmdd}.{summary-kebab}.jpg`, or `{entry_date}.{party-kebab}.{summary-kebab}.jpg` when the JE has a party (if several parties, the party on the largest-magnitude revenue/expense line).

## Docker / release (#18)

HPLIP/SANE setup today requires interactive host configuration. **Containerised API scanning is deferred** until release packaging ([#18](https://github.com/brettski74/TallyBadger/issues/18)); run the API on the host for scanner UAT.

## Troubleshooting

- **503 / scanimage failed:** check device URI, printer awake on LAN, `scanimage -d '…' --source Flatbed --test` (if supported).
- **404:** journal entry id invalid.
- **D-Bus errors** when invoking `scanimage` from a minimal environment: run from a normal user session on the host (same as desktop SANE).
