import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backupDownloadFilename,
  exportBackup,
  exportBackupToDisk,
  exportCompleteBackup,
  importBackup,
  importCompleteBackup,
  isTarGzBackupFile,
} from "./backup";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("backup API", () => {
  it("backupDownloadFilename uses local time and export kind", () => {
    const at = new Date(2026, 4, 3, 14, 9, 7);
    expect(backupDownloadFilename("complete", at)).toBe("tallybadger-complete-20260503-140907.tar.gz");
    expect(backupDownloadFilename("configuration", at)).toBe("tallybadger-config-20260503-140907.tar.gz");
    expect(backupDownloadFilename("financial", at)).toBe("tallybadger-financial-20260503-140907.tar.gz");
  });

  it("isTarGzBackupFile detects tar.gz and zip by name and type", () => {
    expect(isTarGzBackupFile(new File(["x"], "snap.tar.gz"))).toBe(true);
    expect(isTarGzBackupFile(new File(["x"], "snap.tgz"))).toBe(true);
    expect(isTarGzBackupFile(new File(["x"], "snap.zip"))).toBe(false);
    expect(isTarGzBackupFile(new File(["x"], "snap.tar.gz", { type: "application/gzip" }))).toBe(true);
    expect(isTarGzBackupFile(new File(["x"], "snap.zip", { type: "application/zip" }))).toBe(false);
  });

  it("exportBackup POSTs /backup/export with export_type and returns blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["gzip-bytes"]), {
        status: 200,
        headers: { "Content-Type": "application/gzip" },
      }),
    );
    const blob = await exportBackup("configuration");
    expect(blob.size).toBeGreaterThan(0);
    expect(typeof blob.arrayBuffer).toBe("function");
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/export");
    expect(call[0]).toContain("export_type=configuration");
    expect((call[1] as RequestInit).method).toBe("POST");
  });

  it("exportBackupToDisk streams response body to File System Access API when available", async () => {
    const pipeTo = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      body: { pipeTo },
    } as unknown as Response);

    const writable = {};
    const createWritable = vi.fn().mockResolvedValue(writable);
    const showSaveFilePicker = vi.fn().mockResolvedValue({ createWritable });
    Object.assign(window, { showSaveFilePicker });

    await exportBackupToDisk("complete");

    expect(showSaveFilePicker).toHaveBeenCalledWith(
      expect.objectContaining({ suggestedName: expect.stringMatching(/\.tar\.gz$/) }),
    );
    expect(createWritable).toHaveBeenCalled();
    expect(pipeTo).toHaveBeenCalledWith(writable);
  });

  it("exportBackupToDisk falls back to blob download when File System Access API is unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["fallback"]), { status: 200, headers: { "Content-Type": "application/gzip" } }),
    );
    const click = vi.fn();
    const anchor = { href: "", download: "", click } as unknown as HTMLAnchorElement;
    const createElement = vi.spyOn(document, "createElement").mockReturnValue(anchor);
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    await exportBackupToDisk("financial");

    expect(createElement).toHaveBeenCalledWith("a");
    expect(anchor.download).toMatch(/tallybadger-financial-.*\.tar\.gz$/);
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });

  it("exportCompleteBackup still requests complete export", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["z"]), { status: 200, headers: { "Content-Type": "application/gzip" } }),
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

  it("importBackup POSTs raw gzip body with restore_mode query for tar.gz", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "imported" }), { status: 200 }),
    );
    const file = new File(["gzip"], "snap.tar.gz", { type: "application/gzip" });
    await importBackup(file, "overwrite");
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/import?");
    expect(call[0]).toContain("restore_mode=overwrite");
    const init = call[1] as RequestInit & { duplex?: string };
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/gzip" });
    if (typeof file.stream === "function") {
      expect(init.duplex).toBe("half");
    } else {
      expect(init.body).toBe(file);
    }
  });

  it("importBackup POSTs raw zip body with restore_mode query for legacy zip", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importBackup(file, "overwrite");
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/import?");
    expect(call[0]).toContain("restore_mode=overwrite");
    const init = call[1] as RequestInit & { duplex?: string };
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/zip" });
    if (typeof file.stream === "function") {
      expect(init.duplex).toBe("half");
    } else {
      expect(init.body).toBe(file);
    }
  });

  it("importCompleteBackup defaults restore_mode to abort", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importCompleteBackup(file);
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("restore_mode=abort");
  });
});
