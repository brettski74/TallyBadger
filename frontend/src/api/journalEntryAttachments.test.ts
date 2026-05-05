import { describe, expect, it } from "vitest";

import { attachmentMimeSupportsInlinePreview } from "./journalEntryAttachments";

describe("attachmentMimeSupportsInlinePreview", () => {
  it("allows jpeg, png, and pdf with optional parameters", () => {
    expect(attachmentMimeSupportsInlinePreview("image/jpeg")).toBe(true);
    expect(attachmentMimeSupportsInlinePreview("image/jpg")).toBe(true);
    expect(attachmentMimeSupportsInlinePreview("image/png")).toBe(true);
    expect(attachmentMimeSupportsInlinePreview("application/pdf")).toBe(true);
    expect(attachmentMimeSupportsInlinePreview('image/jpeg; charset="binary"')).toBe(true);
  });

  it("rejects other types", () => {
    expect(attachmentMimeSupportsInlinePreview("text/plain")).toBe(false);
    expect(attachmentMimeSupportsInlinePreview("image/gif")).toBe(false);
    expect(attachmentMimeSupportsInlinePreview("application/octet-stream")).toBe(false);
  });
});
