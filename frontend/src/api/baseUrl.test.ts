import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiBase, resolveApiHostname } from "./baseUrl";

describe("baseUrl", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolveApiHostname maps localhost to 127.0.0.1", () => {
    vi.stubGlobal("window", {
      location: { hostname: "localhost", protocol: "http:" },
    });
    expect(resolveApiHostname()).toBe("127.0.0.1");
  });

  it("resolveApiHostname maps ::1 to 127.0.0.1", () => {
    vi.stubGlobal("window", {
      location: { hostname: "::1", protocol: "http:" },
    });
    expect(resolveApiHostname()).toBe("127.0.0.1");
  });

  it("getApiBase uses document origin when not in Vite dev (e.g. Vitest)", () => {
    vi.stubGlobal("window", {
      location: {
        hostname: "localhost",
        protocol: "http:",
        origin: "http://localhost:3000",
      },
    });
    const base = getApiBase();
    if (import.meta.env.DEV) {
      expect(base).toBe("");
    } else {
      expect(base).toBe("http://localhost:3000");
    }
  });
});
