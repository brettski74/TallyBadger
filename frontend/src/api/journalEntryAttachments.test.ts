import { afterEach, describe, expect, it, vi } from "vitest";

import {
  attachmentMimeSupportsInlinePreview,
  attachmentUploadLimitMessage,
  isAttachmentOverUploadLimit,
  uploadJournalEntryAttachment,
} from "./journalEntryAttachments";

afterEach(() => {
  vi.restoreAllMocks();
});

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

describe("attachment upload size", () => {
  const maxBytes = 5_242_880;

  it("formats limit message like the API", () => {
    expect(attachmentUploadLimitMessage(maxBytes)).toBe(
      "attachment exceeds maximum size of 5242880 bytes",
    );
  });

  it("rejects oversized files before fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const file = new File([new Uint8Array(10_485_760)], "big.bin");
    await expect(
      uploadJournalEntryAttachment(1, {
        file,
        summary: "too big",
        maxUploadBytes: maxBytes,
      }),
    ).rejects.toThrow(attachmentUploadLimitMessage(maxBytes));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("maps network errors on oversized uploads to the limit message", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("NetworkError when attempting to fetch resource."),
    );
    const file = new File([new Uint8Array(10_485_760)], "big.bin");
    await expect(
      uploadJournalEntryAttachment(1, {
        file,
        summary: "too big",
        maxUploadBytes: maxBytes,
      }),
    ).rejects.toThrow(attachmentUploadLimitMessage(maxBytes));
  });

  it("allows files at the limit", () => {
    expect(isAttachmentOverUploadLimit(maxBytes, maxBytes)).toBe(false);
    expect(isAttachmentOverUploadLimit(maxBytes + 1, maxBytes)).toBe(true);
  });
});
