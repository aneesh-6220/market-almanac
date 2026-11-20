import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import demo from "@/lib/__fixtures__/investigation-demo.json";
import fixture from "@/lib/__fixtures__/economic-context.json";
import { EconomicEvidence, EconomicSection, isAvailable } from "@/lib/economic-context";
import { contextPins, exportUrl, type Investigation, InvestigationSchema, permalink } from "@/lib/investigation-api";

import { EconomicContext } from "./economic-context";

// ECharts needs a canvas; the charts' data and options are what these tests care about.
const charts = vi.hoisted(() => ({ options: [] as unknown[] }));
vi.mock("@/components/chart", () => ({
  usePalette: () => ({ ink: "#111", ink2: "#222", ink3: "#333", line: "#ddd", surface: "#fff", rain: "#06c", grain: "#c90", heat: "#c30", good: "#080", warn: "#c60", neutral: "#888", bad: "#c00", rainSoft: "#cde", grainSoft: "#fec" }),
  baseOption: () => ({ legend: {}, xAxis: {}, yAxis: {}, tooltip: {} }),
  Chart: ({ option, ariaLabel }: { option: unknown; ariaLabel: string }) => {
    charts.options.push(option);
    return <div role="img" aria-label={ariaLabel} data-testid="chart" />;
  },
}));

const base = InvestigationSchema.parse(demo.investigation);
const doc = (k: "full" | "missing_food" | "not_installed"): Investigation => {
  const f = fixture[k];
  return {
    ...base,
    context: { ...base.context, economic: EconomicSection.parse(f.economic) },
    evidence: { ...base.evidence, economic: f.evidence ? EconomicEvidence.parse(f.evidence) : undefined },
  };
};

describe("the economic-context schemas", () => {
  it("accept what the API returns: full, a country without a food index, and a deployment without the artefact", () => {
    for (const k of ["full", "missing_food", "not_installed"] as const) {
      const r = EconomicSection.safeParse(fixture[k].economic);
      expect(r.success, `${k}: ${JSON.stringify(r.error?.issues?.[0])}`).toBe(true);
    }
    for (const k of ["full", "missing_food"] as const) {
      const r = EconomicEvidence.safeParse(fixture[k].evidence);
      expect(r.success, `${k}: ${JSON.stringify(r.error?.issues?.[0])}`).toBe(true);
    }
  });
  it("keep v1.3 investigations, which have no economic section, valid", () => {
    expect(base.context.economic).toBeUndefined();
    expect(base.evidence.economic).toBeUndefined();
  });
  it("reject a section that lacks its identity", () => {
    const bad = { ...(fixture.full.economic as Record<string, unknown>) };
    delete bad.context_id;
    expect(EconomicSection.safeParse(bad).success).toBe(false);
  });
});

describe("links and exports carry the context pin", () => {
  it("pins the context snapshot in the permalink and the exports, and the as-of month when set", () => {
    const d = doc("full");
    const e = d.context.economic!;
    expect(isAvailable(e)).toBe(true);
    const pins = contextPins(d);
    expect(pins.context).toBe((e as { snapshot: { snapshot_id: string } }).snapshot.snapshot_id);
    expect(new URL(permalink("https://x.test", d)).searchParams.get("context")).toBe(pins.context);
    expect(new URL(exportUrl(d, "csv", { table: "economic_changes" })).searchParams.get("context")).toBe(pins.context);
    expect(new URL(permalink("https://x.test", d, false)).searchParams.has("context")).toBe(false);
  });
  it("adds no pin when the context was unavailable", () => {
    expect(contextPins(doc("not_installed"))).toEqual({});
    expect(new URL(permalink("https://x.test", doc("not_installed"))).searchParams.has("context")).toBe(false);
  });
});

describe("EconomicContext", () => {
  it("says plainly when the artefact is not installed, and concludes nothing", () => {
    render(<EconomicContext d={doc("not_installed")} asOf={undefined} onAsOf={() => {}} />);
    const box = screen.getByTestId("economic-unavailable");
    expect(box).toHaveAttribute("data-state", "not_installed");
    expect(box).toHaveTextContent(/not installed on this deployment/i);
    expect(box).toHaveTextContent(/not evidence that they were unrelated/i);
    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("shows the changes side by side, with the reading note that separates one price from general inflation", () => {
    render(<EconomicContext d={doc("full")} asOf={undefined} onAsOf={() => {}} />);
    expect(screen.getByTestId("economic-reading-note")).toHaveTextContent(/not a rise in the general price level/);
    const table = screen.getByTestId("economic-glance");
    expect(within(table).getByText(/Consumer prices, all items/)).toBeInTheDocument();
    expect(within(table).getByText(/Local price, nominal/)).toBeInTheDocument();
    expect(screen.getAllByTestId("chart").length).toBeGreaterThanOrEqual(2);
  });

  it("reports a missing food index as missing, with the reason, never as a number", () => {
    render(<EconomicContext d={doc("missing_food")} asOf={undefined} onAsOf={() => {}} />);
    const row = screen.getByTestId("economic-missing-food");
    expect(row).toHaveTextContent(/published but empty/);
    expect(row).toHaveTextContent(/empty in the source/);
    expect(row.textContent).not.toMatch(/[+−-]?\d+(\.\d+)?%/);
  });

  it("lists the propositions with an assessment each and keeps causal wording to what is not established", () => {
    render(<EconomicContext d={doc("full")} asOf={undefined} onAsOf={() => {}} />);
    const props = screen.getByTestId("economic-propositions");
    expect(within(props).getAllByRole("listitem").length).toBeGreaterThanOrEqual(3);
    const causal = /\b(caused|because of|due to|drove|driven by|led to|resulted in|explains)\b/i;
    expect(props.textContent).not.toMatch(causal);
    expect(screen.getByText(/What this context does not establish/)).toBeInTheDocument();
  });

  it("names the quote direction of the exchange rate", () => {
    render(<EconomicContext d={doc("full")} asOf={undefined} onAsOf={() => {}} />);
    expect(screen.getByText(/Quote: domestic currency per US dollar/)).toBeInTheDocument();
  });

  it("applies and clears an as-of month through the callback", () => {
    const calls: (string | null)[] = [];
    render(<EconomicContext d={doc("full")} asOf="2024-09" onAsOf={(m) => calls.push(m)} />);
    fireEvent.change(screen.getByLabelText("As-of month"), { target: { value: "2024-08" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    fireEvent.click(screen.getByRole("button", { name: "Show all months" }));
    expect(calls).toEqual(["2024-08", null]);
  });

  it("marks current-vintage readings as exploratory and shows lineage hashes", () => {
    render(<EconomicContext d={doc("full")} asOf={undefined} onAsOf={() => {}} />);
    expect(screen.getByTestId("economic-asof-note")).toHaveTextContent(/exploratory/);
    expect(screen.getByTestId("economic-lineage")).toHaveTextContent(/SHA-256/);
  });

  it("does not turn a missing month into a zero in any chart line", () => {
    charts.options.length = 0;
    render(<EconomicContext d={doc("full")} asOf={undefined} onAsOf={() => {}} />);
    const gaps = (doc("full").context.economic as { price: { chart_index: (number | null)[] } }).price.chart_index;
    for (const o of charts.options as { series: { data: (number | null)[] }[] }[]) {
      for (const s of o.series) expect(s.data.filter((v) => v === 0)).toEqual(gaps.filter((v) => v === 0));
    }
  });
});
