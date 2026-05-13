/**
 * First path segment after `/` for requests the Vite dev server must proxy to FastAPI.
 * Keep in sync with `vite.config.ts` `devProxy` keys (each `/${prefix}`).
 *
 * If a new API top-level route is added but not listed here, the browser receives SPA
 * `index.html` (200) instead of JSON, and `response.json()` fails with a parse error.
 */
export const DEV_SERVER_API_PROXY_PREFIXES = [
  "accrual-plans",
  "accounts",
  "backup",
  "cheques",
  "health",
  "import-rules",
  "import-templates",
  "imports",
  "journal-entries",
  "journal-entry-filter-presets",
  "ledger-settings",
  "obligations",
  "parties",
  "reports",
  "settlements",
] as const;
