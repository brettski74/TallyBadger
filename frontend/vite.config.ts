import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

import { DEV_SERVER_API_PROXY_PREFIXES } from "./src/devServerApiProxyPrefixes";

/** FastAPI (tbad / uvicorn) — proxied in dev so the browser only talks to the Vite origin (no loopback/CORS issues). */
const API_DEV_TARGET = "http://127.0.0.1:8080";

const devProxy = Object.fromEntries(
  DEV_SERVER_API_PROXY_PREFIXES.map((prefix) => [
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
