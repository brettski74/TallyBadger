import { describe, expect, it } from "vitest";

import { isTargetAssociatedWithForm } from "./useFormSaveRevertShortcuts";

describe("isTargetAssociatedWithForm", () => {
  it("treats light-DOM descendants of the form as associated", () => {
    const form = document.createElement("form");
    const input = document.createElement("input");
    form.appendChild(input);
    document.body.appendChild(form);
    expect(isTargetAssociatedWithForm(input, form)).toBe(true);
    form.remove();
  });

  it("treats focus targets inside an open shadow root under the form as associated", () => {
    const form = document.createElement("form");
    const host = document.createElement("div");
    form.appendChild(host);
    document.body.appendChild(form);
    const shadow = host.attachShadow({ mode: "open" });
    const inner = document.createElement("input");
    shadow.appendChild(inner);

    expect(form.contains(inner)).toBe(false);
    expect(isTargetAssociatedWithForm(inner, form)).toBe(true);

    form.remove();
  });

  it("honours form= on controls outside the form subtree", () => {
    const form = document.createElement("form");
    form.id = "jf-test-remote-form";
    const input = document.createElement("input");
    input.setAttribute("form", "jf-test-remote-form");
    document.body.appendChild(form);
    document.body.appendChild(input);

    expect(form.contains(input)).toBe(false);
    expect(isTargetAssociatedWithForm(input, form)).toBe(true);

    input.remove();
    form.remove();
  });

  it("returns false when the node is not related to the form", () => {
    const form = document.createElement("form");
    const other = document.createElement("input");
    document.body.append(form, other);
    expect(isTargetAssociatedWithForm(other, form)).toBe(false);
    form.remove();
    other.remove();
  });
});
