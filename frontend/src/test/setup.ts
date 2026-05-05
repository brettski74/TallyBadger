import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/** jsdom does not implement `<dialog>.showModal()`; keep modal tests aligned with browser behaviour. */
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModalPolyfill(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
}

afterEach(() => {
  cleanup();
});
