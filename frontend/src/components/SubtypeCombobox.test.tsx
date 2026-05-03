import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { filterSubtypeOptions, subtypeCompletionSuffix, SubtypeCombobox } from "./SubtypeCombobox";

function SubtypeWrap({
  initial = "",
  suggestions = ["Tenant", "Utilities"],
}: {
  initial?: string;
  suggestions?: string[];
}) {
  const [v, setV] = useState(initial);
  return <SubtypeCombobox aria-label="Test subtype" value={v} onChange={setV} suggestions={suggestions} />;
}

describe("filterSubtypeOptions", () => {
  it("returns empty for blank query", () => {
    expect(filterSubtypeOptions("", ["Tenant", "Utilities"])).toEqual([]);
    expect(filterSubtypeOptions("   ", ["Tenant"])).toEqual([]);
  });

  it("prefix-matches case-insensitively and dedupes", () => {
    expect(filterSubtypeOptions("ten", ["Tenant", "tenant", "Utilities"])).toEqual(["Tenant"]);
  });

  it("sorts and caps", () => {
    const many = [
      "Zebra",
      "Apple",
      "Apricot",
      "Banana",
      "Bay",
      "Cedar",
      "Cypress",
      "Daff",
      "Elm",
      "Fir",
      "Gum",
      "Hickory",
      "Ironwood",
      "Juniper",
      "Kapok",
      "Larch",
      "Maple",
      "Oak",
      "Pine",
      "Quince",
      "Redwood",
      "Spruce",
      "Teak",
      "Ulmus",
      "Vine",
      "Walnut",
    ];
    const out = filterSubtypeOptions("a", many);
    expect(out.length).toBeLessThanOrEqual(20);
    expect(out[0]).toBe("Apple");
  });
});

describe("subtypeCompletionSuffix", () => {
  it("returns remainder with canonical casing", () => {
    expect(subtypeCompletionSuffix("Te", "Tenant")).toBe("nant");
    expect(subtypeCompletionSuffix("tenant", "Tenant")).toBe("");
  });
});

describe("SubtypeCombobox", () => {
  it("shows ghost suffix while typing and accepts on Enter", async () => {
    render(<SubtypeWrap />);

    const user = userEvent.setup();
    const input = screen.getByRole("textbox", { name: "Test subtype" });
    await user.click(input);
    await user.type(input, "Ut");

    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("ilities");

    await user.keyboard("{Enter}");
    expect(input).toHaveValue("Utilities");
  });

  it("hides ghost on Escape until user edits again", async () => {
    render(<SubtypeWrap initial="Ut" />);

    const user = userEvent.setup();
    const input = screen.getByRole("textbox", { name: "Test subtype" });
    await user.click(input);
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("ilities");

    await user.keyboard("{Escape}");
    expect(document.querySelector(".subtype-ghost-suffix")).not.toBeInTheDocument();

    await user.type(input, "i");
    expect(document.querySelector(".subtype-ghost-suffix")).toHaveTextContent("lities");
  });
});
