import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backupDownloadFilename,
  exportBackup,
  exportCompleteBackup,
  importBackup,
  importCompleteBackup,
} from "./backup";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("backup API", () => {
  it("backupDownloadFilename uses local time and export kind", () => {
    const at = new Date(2026, 4, 3, 14, 9, 7);
    expect(backupDownloadFilename("complete", at)).toBe("tallybadger-complete-20260503-140907.zip");
    expect(backupDownloadFilename("configuration", at)).toBe("tallybadger-config-20260503-140907.zip");
    expect(backupDownloadFilename("financial", at)).toBe("tallybadger-financial-20260503-140907.zip");
  });

  it("exportBackup POSTs /backup/export with export_type and returns blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["zip-bytes"]), {
        status: 200,
        headers: { "Content-Type": "application/zip" },
      }),
    );
    const blob = await exportBackup("configuration");
    // jsdom/Vitest can return a Blob from another realm where `instanceof Blob` fails.
    expect(blob.size).toBeGreaterThan(0);
    expect(typeof blob.arrayBuffer).toBe("function");
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/export");
    expect(call[0]).toContain("export_type=configuration");
    expect((call[1] as RequestInit).method).toBe("POST");
  });

  it("exportCompleteBackup still requests complete export", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["z"]), { status: 200, headers: { "Content-Type": "application/zip" } }),
    );
    await exportCompleteBackup();
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("export_type=complete");
  });

  it("importBackup returns formatDeprecationWarning when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "imported",
          format_deprecation_warning: "Older format 1.5.0 is deprecated.",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    const result = await importBackup(file);
    expect(result.formatDeprecationWarning).toBe("Older format 1.5.0 is deprecated.");
  });

  it("importBackup POSTs multipart with restore_mode", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importBackup(file, "overwrite");
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/import");
    const init = call[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect([...(init.body as FormData).entries()]).toEqual(
      expect.arrayContaining([
        ["snapshot", file],
        ["restore_mode", "overwrite"],
      ]),
    );
  });

  it("importCompleteBackup defaults restore_mode to abort", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importCompleteBackup(file);
    const init = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0][1] as RequestInit;
    expect((init.body as FormData).get("restore_mode")).toBe("abort");
  });
});
