import { describe, expect, it } from "vitest";

import fixture from "./__fixtures__/investigation-demo.json";
import { configParams, exportUrl, InvestigationSchema, permalink, ShockPageSchema, zText } from "./investigation-api";

/* The fixture is real API output on the synthetic demo (scripts/ops/investigation_fixture.py; regenerate when the
   document changes). Parsing it here catches drift between the API and these schemas before a browser does. */

describe("schemas accept what the API returns", () => {
  it("parses a discovery page", () => {
    const r = ShockPageSchema.safeParse(fixture.shocks);
    expect(r.success, JSON.stringify(r.error?.issues?.[0])).toBe(true);
  });
  it("parses an investigation, including peers that could not be assessed", () => {
    const doc = structuredClone(fixture.investigation) as Record<string, unknown> & { peers: { rows: Record<string, unknown>[] } };
    doc.peers.rows.push({ ...doc.peers.rows[0], status: "withheld", reason: "short history", z: null, yoy_pct: null, elevated: null });
    const r = InvestigationSchema.safeParse(doc);
    expect(r.success, JSON.stringify(r.error?.issues?.[0])).toBe(true);
  });
});

describe("reproducibility", () => {
  const d = InvestigationSchema.parse(fixture.investigation);
  it("builds a permalink that pins the month and the window", () => {
    const p = configParams(d);
    expect(permalink("https://example.org", d)).toBe(
      `https://example.org/investigate?series=${d.config.series_id}&event=${p.event}&start=${p.start}&end=${p.end}`,
    );
  });
  it("exports with the same configuration", () => {
    const u = new URL(exportUrl(d, "csv", { table: "peers" }));
    expect(u.pathname).toBe(`/api/v1/investigations/${d.config.series_id}/export`);
    expect(Object.fromEntries(u.searchParams)).toMatchObject({ ...configParams(d), format: "csv", table: "peers" });
  });
});

describe("zText", () => {
  it("shows one decimal within +/-10 and no false precision beyond", () => {
    expect(zText(3.24)).toBe("+3.2");
    expect(zText(-2.05)).toBe("-2.0");
    expect(zText(145.7)).toBe("beyond +10");
    expect(zText(-12)).toBe("beyond −10");
    expect(zText(null)).toBe("—");
  });
});
