const API_PORT = import.meta.env.VITE_API_PORT ?? "8080";

/**
 * Hostname for explicit API URL (production / tests). Not used when Vite dev proxy is active.
 */
export function resolveApiHostname(): string {
  const h = window.location.hostname;
  if (h === "localhost" || h === "127.0.0.1") {
    return "127.0.0.1";
  }
  if (h === "::1") {
    return "127.0.0.1";
  }
  return h;
}

/**
 * Base URL for API requests (no trailing slash).
 *
 * - **Vite dev** (`import.meta.env.DEV`): returns `""` so fetches use paths like `/accounts`, which the
 *   dev server proxies to FastAPI (see ``vite.config.ts`` and ``src/devServerApiProxyPrefixes.ts``). Avoids browser issues with
 *   `localhost` vs `127.0.0.1` / IPv6 loopback.
 * - **``VITE_API_BASE_URL``** set: always use that (any mode).
 * - **Production build**: same document origin (set ``VITE_API_BASE_URL`` if the API is elsewhere).
 */
export function getApiBase(): string {
  const explicit = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (explicit) {
    return explicit.replace(/\/$/, "");
  }
  if (import.meta.env.DEV) {
    return "";
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return `http://127.0.0.1:${API_PORT}`;
}
