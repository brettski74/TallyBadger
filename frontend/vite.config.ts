import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** FastAPI (tbad / uvicorn) — proxied in dev so the browser only talks to the Vite origin (no loopback/CORS issues). */
const API_DEV_TARGET = "http://127.0.0.1:8080";

const apiProxyPrefixes = [
  "reports",
  "backup",
  "cheques",
  "accounts",
  "parties",
  "journal-entries",
  "ledger-settings",
  "obligations",
  "settlements",
  "accrual-plans",
  "import-templates",
  "import-rules",
  "imports",
  "health",
] as const;

const devProxy = Object.fromEntries(
  apiProxyPrefixes.map((prefix) => [
    `/${prefix}`,
    { target: API_DEV_TARGET, changeOrigin: true },
  ]),
);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: devProxy,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    reporters: ["default", "junit"],
    outputFile: {
      junit: "../test-results/frontend-vitest.xml",
    },
  },
});
