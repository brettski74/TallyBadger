import { describe, expect, it } from "vitest";

import { DEV_SERVER_API_PROXY_PREFIXES } from "./devServerApiProxyPrefixes";

describe("DEV_SERVER_API_PROXY_PREFIXES", () => {
  it("includes import-batches for dev proxy JSON", () => {
    expect(DEV_SERVER_API_PROXY_PREFIXES).toContain("import-batches");
  });

  it("includes cheque-register-filter-presets for dev proxy JSON", () => {
    expect(DEV_SERVER_API_PROXY_PREFIXES).toContain("cheque-register-filter-presets");
  });

  it("has no duplicate prefixes", () => {
    const set = new Set(DEV_SERVER_API_PROXY_PREFIXES);
    expect(set.size).toBe(DEV_SERVER_API_PROXY_PREFIXES.length);
  });
});
