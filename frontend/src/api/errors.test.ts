import { describe, expect, it } from "vitest";

import { messageFromErrorBody } from "./errors";

describe("messageFromErrorBody", () => {
  it("reads string detail", () => {
    expect(messageFromErrorBody({ detail: "journal entry is not balanced" })).toBe(
      "journal entry is not balanced",
    );
  });

  it("joins Pydantic validation list messages", () => {
    expect(
      messageFromErrorBody({
        detail: [{ msg: "field required" }, { msg: "invalid type" }],
      }),
    ).toBe("field required; invalid type");
  });

  it("returns null for unknown shapes", () => {
    expect(messageFromErrorBody(null)).toBeNull();
    expect(messageFromErrorBody({})).toBeNull();
  });
});
