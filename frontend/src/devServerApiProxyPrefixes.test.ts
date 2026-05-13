import { describe, expect, it } from "vitest";

import { DEV_SERVER_API_PROXY_PREFIXES } from "./devServerApiProxyPrefixes";

describe("DEV_SERVER_API_PROXY_PREFIXES", () => {
  it("includes journal-entry-filter-presets so the dev proxy returns JSON, not index.html", () => {
    expect(DEV_SERVER_API_PROXY_PREFIXES).toContain("journal-entry-filter-presets");
  });

  it("has no duplicate prefixes", () => {
    const set = new Set(DEV_SERVER_API_PROXY_PREFIXES);
    expect(set.size).toBe(DEV_SERVER_API_PROXY_PREFIXES.length);
  });
});
