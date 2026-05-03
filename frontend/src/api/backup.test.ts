import { afterEach, describe, expect, it, vi } from "vitest";

import { exportBackup, exportCompleteBackup, importBackup, importCompleteBackup } from "./backup";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("backup API", () => {
  it("exportBackup POSTs /backup/export with export_type and returns blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["zip-bytes"]), {
        status: 200,
        headers: { "Content-Type": "application/zip" },
      }),
    );
    const blob = await exportBackup("configuration");
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBeGreaterThan(0);
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

  it("importBackup POSTs multipart with duplicate_policy", async () => {
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
        ["duplicate_policy", "overwrite"],
      ]),
    );
  });

  it("importCompleteBackup defaults duplicate_policy to abort", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importCompleteBackup(file);
    const init = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0][1] as RequestInit;
    expect((init.body as FormData).get("duplicate_policy")).toBe("abort");
  });
});
