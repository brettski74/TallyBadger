import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { filterSubtypeOptions, SubtypeCombobox } from "./SubtypeCombobox";

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

describe("SubtypeCombobox", () => {
  it("accepts highlighted suggestion on Enter", async () => {
    render(<SubtypeWrap />);

    const user = userEvent.setup();
    const input = screen.getByRole("combobox", { name: "Test subtype" });
    await user.click(input);
    await user.type(input, "Ut");

    expect(await screen.findByRole("option", { name: "Utilities" })).toBeInTheDocument();
    await user.keyboard("{Enter}");

    expect(input).toHaveValue("Utilities");
  });

  it("dismisses list on Escape until user edits again", async () => {
    render(<SubtypeWrap initial="Ut" />);

    const user = userEvent.setup();
    const input = screen.getByRole("combobox", { name: "Test subtype" });
    await user.click(input);
    expect(await screen.findByRole("option", { name: "Utilities" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("option", { name: "Utilities" })).not.toBeInTheDocument();

    await user.type(input, "i");
    expect(input).toHaveValue("Uti");
    expect(await screen.findByRole("option", { name: "Utilities" })).toBeInTheDocument();
  });
});
