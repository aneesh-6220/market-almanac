import { describe, expect, it } from "vitest";

import { fmt, modelLabel, month, pct, pValue, toCsv } from "./format";

describe("number formatting", () => {
  it("shows a dash for missing or non-finite values instead of zero", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt(undefined)).toBe("—");
    expect(fmt(Number.NaN)).toBe("—");
    expect(pct(Number.POSITIVE_INFINITY)).toBe("—");
    expect(pValue(null)).toBe("—");
  });

  it("formats significant digits, percentages and small p-values", () => {
    expect(fmt(0.758672)).toBe("0.759");
    expect(fmt(12345.6)).toMatch(/12,346/);
    expect(pct(0.2054, 1)).toBe("20.5%");
    expect(pValue(0.0004)).toBe("< 0.001");
    expect(pValue(0.0123)).toBe("0.012");
  });

  it("formats months in UTC regardless of local time zone", () => {
    expect(month("2025-11-01")).toBe("Nov 2025");
    expect(month("2016-01")).toBe("Jan 2016");
    expect(month(null)).toBe("—");
  });

  it("labels models in plain language and falls back to the id", () => {
    expect(modelLabel("ridge_B")).toContain("weather");
    expect(modelLabel("unknown_model")).toBe("unknown_model");
  });
});

describe("CSV export", () => {
  it("quotes values containing commas, quotes or newlines", () => {
    const csv = toCsv([{ a: "x,y", b: 'say "hi"', c: null, d: 3 }]);
    expect(csv).toBe('a,b,c,d\n"x,y","say ""hi""",,3');
  });
  it("returns an empty string for no rows", () => {
    expect(toCsv([])).toBe("");
  });
});
