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

  it("labels known fields and rewrites greater-than-zero messages", () => {
    expect(
      messageFromErrorBody({
        detail: [
          {
            type: "greater_than",
            loc: ["body", "party_id"],
            msg: "Input should be greater than 0",
            input: 0,
          },
        ],
      }),
    ).toBe("Select a party.");
  });

  it("prefixes other validation messages with field labels", () => {
    expect(
      messageFromErrorBody({
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "name"],
            msg: "String should have at least 1 character",
            input: "",
          },
        ],
      }),
    ).toBe("Plan name: String should have at least 1 character");
  });

  it("returns null for unknown shapes", () => {
    expect(messageFromErrorBody(null)).toBeNull();
    expect(messageFromErrorBody({})).toBeNull();
  });
});
