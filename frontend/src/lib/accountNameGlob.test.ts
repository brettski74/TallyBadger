import { describe, expect, it } from "vitest";

import { accountNameMatchesGlob } from "./accountNameGlob";

describe("accountNameMatchesGlob", () => {
  it("matches * and ? case-insensitively", () => {
    expect(accountNameMatchesGlob("Petty Cash", "petty*cash")).toBe(true);
    expect(accountNameMatchesGlob("Petty Cash", "petty?cash")).toBe(true);
    expect(accountNameMatchesGlob("Petty Cash", "PETTY*")).toBe(true);
    expect(accountNameMatchesGlob("Petty Cash", "*cash")).toBe(true);
    expect(accountNameMatchesGlob("Petty Cash", "other*")).toBe(false);
  });

  it("treats regex metacharacters in pattern as literals (glob wildcards are only * and ?)", () => {
    expect(accountNameMatchesGlob("a.b", "a.b")).toBe(true);
    expect(accountNameMatchesGlob("axb", "a.b")).toBe(false);
  });
});
