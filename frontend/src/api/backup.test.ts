import { afterEach, describe, expect, it, vi } from "vitest";

import { exportCompleteBackup, importCompleteBackup } from "./backup";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("backup API", () => {
  it("exportCompleteBackup POSTs /backup/export and returns blob", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["zip-bytes"]), {
        status: 200,
        headers: { "Content-Type": "application/zip" },
      }),
    );
    const blob = await exportCompleteBackup();
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBeGreaterThan(0);
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/export");
    expect((call[1] as RequestInit).method).toBe("POST");
  });

  it("importCompleteBackup POSTs multipart to /backup/import", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "imported" }), { status: 200 }));
    const file = new File(["x"], "snap.zip", { type: "application/zip" });
    await importCompleteBackup(file);
    const call = (globalThis.fetch as ReturnType<typeof vi.spyOn>).mock.calls[0];
    expect(call[0]).toContain("/backup/import");
    const init = call[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });
});
