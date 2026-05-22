import { describe, expect, it } from "vitest";

import { isNewChord } from "./keyboardChords";

describe("isNewChord", () => {
  it("matches Ctrl+N when key is the letter n", () => {
    expect(
      isNewChord({ key: "n", code: "KeyN", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false } as KeyboardEvent),
    ).toBe(true);
  });

  it("matches Ctrl+N when key is a control character but code is KeyN (Firefox/Linux)", () => {
    expect(
      isNewChord({ key: "\u000e", code: "KeyN", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false } as KeyboardEvent),
    ).toBe(true);
  });

  it("rejects Ctrl+Shift+N", () => {
    expect(
      isNewChord({ key: "n", code: "KeyN", ctrlKey: true, metaKey: false, altKey: false, shiftKey: true } as KeyboardEvent),
    ).toBe(false);
  });
});
