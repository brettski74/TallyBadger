import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/** jsdom does not implement `<dialog>.showModal()` / `.close()`; keep modal tests aligned with browser behaviour. */
if (typeof HTMLDialogElement !== "undefined") {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModalPolyfill(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function closePolyfill(this: HTMLDialogElement) {
      this.removeAttribute("open");
    };
  }
}

afterEach(() => {
  cleanup();
});
