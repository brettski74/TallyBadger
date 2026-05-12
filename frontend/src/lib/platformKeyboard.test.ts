import { describe, expect, it, vi } from "vitest";

import { isMacLikeUserAgent } from "./platformKeyboard";

describe("isMacLikeUserAgent", () => {
  it("returns false for typical Windows jsdom defaults", () => {
    expect(isMacLikeUserAgent()).toBe(false);
  });

  it("returns true when platform looks like macOS", () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      platform: "MacIntel",
      userAgent: "Mozilla/5.0",
    });
    expect(isMacLikeUserAgent()).toBe(true);
    vi.unstubAllGlobals();
  });
});
