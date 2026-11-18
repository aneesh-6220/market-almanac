import { describe, expect, it } from "vitest";

import { comparableQuery, exportUrl, GlobalCountrySchema, GlobalMarketSchema, incompatibility, ObservationSchema, TIER_LABEL } from "./global-api";

const row = { commodity_code: "10", unit: "KG", price_type: "Retail", currency: "AMD" };

describe("incompatibility", () => {
  it("accepts one series or an identical measurement", () => {
    expect(incompatibility([])).toBeNull();
    expect(incompatibility([row])).toBeNull();
    expect(incompatibility([row, { ...row }])).toBeNull();
  });
  it("names the first difference that makes prices incomparable", () => {
    expect(incompatibility([row, { ...row, commodity_code: "11" }])).toMatch(/commodit/);
    expect(incompatibility([row, { ...row, unit: "100 KG" }])).toMatch(/unit/);
    expect(incompatibility([row, { ...row, price_type: "Wholesale" }])).toMatch(/price type/);
  });
  it("allows different currencies only as an indexed comparison, never a conversion", () => {
    const msg = incompatibility([row, { ...row, currency: "NPR" }]);
    expect(msg).toMatch(/different currencies/);
    expect(msg).toMatch(/no conversion/);
  });
});

describe("comparableQuery", () => {
  it("restricts peers to the same commodity, unit, price type and currency", () => {
    expect(comparableQuery(row)).toMatchObject({ commodity: "10", unit: "KG", price_type: "Retail", currency: "AMD" });
  });
});

describe("exportUrl", () => {
  it("builds a download link with the optional window", () => {
    const u = new URL(exportUrl("ps_0123456789abcdef", "csv", "2023-01", "2023-12"));
    expect(u.pathname).toBe("/api/v1/global/series/ps_0123456789abcdef/export");
    expect(u.searchParams.get("format")).toBe("csv");
    expect(u.searchParams.get("start")).toBe("2023-01");
    expect(new URL(exportUrl("ps_0123456789abcdef", "json")).searchParams.has("start")).toBe(false);
  });
});

describe("schemas", () => {
  it("tolerate the nulls the API sends for markets without coordinates and series without prices", () => {
    expect(
      GlobalMarketSchema.parse({
        country_iso3: "TCD",
        market_code: "1",
        market_name: "Abeche",
        admin1_name: null,
        lat: null,
        lon: null,
        coordinate_status: "missing",
        series: 3,
        usable_series: 0,
        commodities: 3,
        first_period: null,
        last_period: null,
        observations: 0,
      }).coordinate_status,
    ).toBe("missing");
    expect(
      ObservationSchema.parse({
        period: "2024-01-01",
        price: null,
        price_flag: null,
        quality_flags: ["missing_price"],
        valid: false,
        used_in_series: false,
        duplicate_month: false,
        reference_period_start: null,
        reference_period_end: null,
        source_ref: null,
        retrieved_at: null,
      }).valid,
    ).toBe(false);
  });
  it("rejects an unknown coordinate status rather than plotting it", () => {
    expect(() => GlobalMarketSchema.parse({ coordinate_status: "weird" })).toThrow();
  });
  it("requires every country to carry its data tier", () => {
    expect(GlobalCountrySchema.safeParse({ country_iso3: "ARM", name: "Armenia" }).success).toBe(false);
  });
});

describe("tier labels", () => {
  it("only the evaluated tiers claim anything about forecasting", () => {
    expect(TIER_LABEL.ingested.text).not.toMatch(/forecast|research/i);
    expect(TIER_LABEL.validated.text).not.toMatch(/forecast|research/i);
    expect(TIER_LABEL.forecast_evaluated.text).toMatch(/evaluated/i);
  });
});
