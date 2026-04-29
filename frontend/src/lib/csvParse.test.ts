import { describe, expect, it } from "vitest";

import { parseCsv } from "./csvParse";

describe("parseCsv", () => {
  it("returns empty array for empty input", () => {
    expect(parseCsv("")).toEqual([]);
  });

  it("parses simple rows", () => {
    expect(parseCsv("a,b\nc,d")).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
  });

  it("handles quoted commas", () => {
    expect(parseCsv('"a,1",b')).toEqual([["a,1", "b"]]);
  });

  it("handles escaped quotes", () => {
    expect(parseCsv('"say ""hi""",x')).toEqual([['say "hi"', "x"]]);
  });

  it("pads short rows to a rectangle", () => {
    expect(parseCsv("a,b\nc")).toEqual([
      ["a", "b"],
      ["c", ""],
    ]);
  });
});
