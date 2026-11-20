"use client";

import { Download } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { baseOption, Chart, type ChartHandle, type Palette, usePalette } from "@/components/chart";
import { LinkButton, signedPct } from "@/components/market-bits";
import { Note, Panel, Tag } from "@/components/ui";
import {
  type Benchmark,
  type EconomicAvailable,
  type EconomicEvidence,
  type EconomicSection,
  type Indicator,
  isAvailable,
  missingMonths,
  stateLabel,
  UNAVAILABLE_TITLE,
} from "@/lib/economic-context";
import { month } from "@/lib/format";
import { exportUrl, type Investigation } from "@/lib/investigation-api";

type Tone = "good" | "neutral" | "warn" | "muted";
const VERDICT_TONE: Record<string, Tone> = {
  consistent: "warn",
  partly_consistent: "neutral",
  less_likely: "muted",
  context_only: "muted",
  cannot_be_assessed: "muted",
};
const INFERENCE_TONE: Record<string, Tone> = { descriptive: "muted", associational: "neutral", predictive: "neutral", causal: "warn" };

const ECONOMIC_TABLES = [
  ["economic_series", "Indexed series"],
  ["economic_changes", "Changes"],
  ["economic_lags", "Lag comparisons"],
  ["economic_lineage", "Sources and hashes"],
  ["economic_notes", "Methods and limits"],
] as const;

export function EconomicContext({
  d,
  asOf,
  onAsOf,
}: {
  d: Investigation;
  asOf: string | undefined;
  onAsOf: (m: string | null) => void;
}) {
  const e = d.context.economic;
  return (
    <Panel
      id="economic"
      title="7. Economic context"
      note="Local prices set beside consumer prices, exchange rates and international benchmarks. Magnitudes are placed side by side; nothing here shows that one moved another."
    >
      {!e ? (
        <Note>This investigation was made before the economic-context engine; open it again without a saved copy to include it.</Note>
      ) : !isAvailable(e) ? (
        <Unavailable e={e} />
      ) : (
        <Available d={d} e={e} ev={d.evidence.economic} asOf={asOf} onAsOf={onAsOf} />
      )}
    </Panel>
  );
}

function Unavailable({ e }: { e: Exclude<EconomicSection, { status: "ok" | "no_context" }> }) {
  return (
    <div data-testid="economic-unavailable" data-state={e.status}>
      <Note>
        <p className="font-medium text-ink">{UNAVAILABLE_TITLE[e.status] ?? "Economic context is not available"}.</p>
        <p className="mt-1">{e.reason}.</p>
      </Note>
      <p className="mt-3 text-sm text-ink-2">
        Nothing about inflation, exchange rates or international prices is concluded or implied. Their absence is a gap in the evidence, not
        evidence that they were unrelated to the price movement.
      </p>
    </div>
  );
}

/* --- available ---------------------------------------------------------------------------------------- */

function Available({
  d,
  e,
  ev,
  asOf,
  onAsOf,
}: {
  d: Investigation;
  e: EconomicAvailable;
  ev: EconomicEvidence | undefined;
  asOf: string | undefined;
  onAsOf: (m: string | null) => void;
}) {
  const cur = d.subject.currency;
  return (
    <div data-testid="economic-available" data-status={e.status}>
      <p className="text-sm text-ink-2" data-testid="economic-reading-note">
        A rise in one food’s price is not a rise in the general price level: a large increase in one price does not imply the same rate of inflation. The figures below
        separate the local price (nominal, in {cur}), general and food inflation, the exchange rate, and international benchmarks, so each can be
        read against the others without being mistaken for them.
      </p>
      <SnapshotLine e={e} asOf={asOf} onAsOf={onAsOf} />
      {e.status === "no_context" && (
        <div className="mt-4">
          <Note>
            No integrated series covers this country and commodity, so there is nothing to set beside the price. The reasons are listed with each
            series below.
          </Note>
        </div>
      )}
      <Warnings e={e} />
      <Glance d={d} e={e} />
      <Charts d={d} e={e} />
      {ev && <Propositions ev={ev} />}
      <Lags e={e} />
      <Gaps e={e} ev={ev} />
      <Lineage e={e} />
      <div className="mt-5 flex flex-wrap gap-2 print:hidden" aria-label="Economic context data">
        {ECONOMIC_TABLES.map(([t, label]) => (
          <LinkButton key={t} href={exportUrl(d, "csv", { table: t })} download>
            <Download className="h-3.5 w-3.5" aria-hidden /> {label} (CSV)
          </LinkButton>
        ))}
      </div>
    </div>
  );
}

function SnapshotLine({ e, asOf, onAsOf }: { e: EconomicAvailable; asOf: string | undefined; onAsOf: (m: string | null) => void }) {
  const [value, setValue] = useState(asOf ?? "");
  return (
    <div className="mt-3 rounded border border-line bg-surface-2 p-3 text-xs text-ink-2">
      <p>
        Context snapshot <code>{e.snapshot.snapshot_id}</code> (identity <code>{e.context_id}</code>). {sentence(e.snapshot.vintage)}.
      </p>
      <form
        className="mt-2 flex flex-wrap items-end gap-2 print:hidden"
        onSubmit={(ev) => {
          ev.preventDefault();
          onAsOf(value || null);
        }}
      >
        <label className="flex flex-col gap-0.5">
          <span className="text-ink-3">Limit to what was assumed published by</span>
          <input
            type="month"
            value={value}
            max={e.window.end}
            onChange={(x) => setValue(x.target.value)}
            className="h-8 rounded border border-line bg-surface px-2 text-sm text-ink"
            aria-label="As-of month"
          />
        </label>
        <button type="submit" className="h-8 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface">
          Apply
        </button>
        {asOf && (
          <button
            type="button"
            className="h-8 text-sm text-rain underline"
            onClick={() => {
              setValue("");
              onAsOf(null);
            }}
          >
            Show all months
          </button>
        )}
      </form>
      <p className="mt-2 text-ink-3" data-testid="economic-asof-note">
        {e.as_of ? (
          <>
            Showing only values assumed published by {month(e.as_of)}. {sentence(e.assumptions.note)}.
          </>
        ) : (
          <>
            All months in the snapshot are shown, including values published after the investigated month: an exploratory reading. {sentence(e.assumptions.note)}.
          </>
        )}
      </p>
    </div>
  );
}

function Warnings({ e }: { e: EconomicAvailable }) {
  if (e.warnings.length === 0) return null;
  return (
    <ul className="mt-4 space-y-2" data-testid="economic-warnings">
      {e.warnings.map((w) => (
        <li key={w.code}>
          <Note tone={w.severity === "info" ? "info" : "warn"}>{w.text}</Note>
        </li>
      ))}
    </ul>
  );
}

/* --- side by side -------------------------------------------------------------------------------------- */

type Row = { key: string; label: string; detail?: string; yoy: number | null | undefined; peak: number | null | undefined; coverage?: Indicator["coverage"]; state: string; reason?: string | null; yoyReason?: string | null; peakReason?: string | null };

function rows(d: Investigation, e: EconomicAvailable): Row[] {
  const price: Row = { key: "price", label: `Local price, nominal (${d.subject.currency} per ${d.subject.unit})`, yoy: e.price.yoy_pct, peak: e.price.baseline_to_peak_pct, state: "ok" };
  const ind = (key: string, i: Indicator, label: string, detail?: string): Row => ({
    key,
    label,
    detail,
    yoy: i.yoy_pct,
    peak: i.baseline_to_peak_pct,
    coverage: i.coverage,
    state: i.state,
    reason: i.reason ?? i.yoy_unavailable_reason,
    yoyReason: i.yoy_unavailable_reason,
    peakReason: i.baseline_to_peak_unavailable_reason,
  });
  const fxOk = e.exchange_rate.applicability === "applies";
  const out: Row[] = [
    price,
    ind("cpi", e.inflation.headline, "Consumer prices, all items (IMF)", "general inflation"),
    ind("food", e.inflation.food, "Consumer prices, food (IMF)", "food inflation"),
    fxOk
      ? ind("fx", e.exchange_rate.period_average, `Exchange rate, ${e.exchange_rate.price_currency} per US dollar (IMF)`, "a rise is a weaker local currency")
      : {
          key: "fx",
          label: "Exchange rate (IMF)",
          yoy: null,
          peak: null,
          state: e.exchange_rate.applicability,
          reason: `not applicable here: ${applicabilityText(e.exchange_rate.applicability)}`,
        },
  ];
  if (e.usd_price)
    out.push({ key: "usd", label: "Local price in US dollars (indicative)", detail: "at the official period-average rate", yoy: e.usd_price.yoy_pct, peak: e.usd_price.baseline_to_peak_pct, state: "ok" });
  for (const b of e.international.items) {
    out.push(ind(`b-${b.series_key}`, b, `${b.label}, US dollars (World Bank)`));
    if (b.local_currency?.yoy_pct != null)
      out.push({
        key: `bl-${b.series_key}`,
        label: `${b.label}, in ${d.subject.currency}`,
        detail: "dollar price × exchange rate",
        yoy: b.local_currency.yoy_pct,
        peak: b.local_currency.baseline_to_peak_pct,
        state: "ok",
      });
  }
  return out;
}

const applicabilityText = (a: string): string =>
  ({
    price_in_usd: "the price is recorded in US dollars",
    dollarized: "the economy uses the US dollar",
    currency_mismatch: "the price currency differs from the national currency of the exchange-rate series",
    no_series: "no exchange-rate series is integrated for this country",
  })[a] ?? a.replaceAll("_", " ");

function Glance({ d, e }: { d: Investigation; e: EconomicAvailable }) {
  const rs = rows(d, e);
  return (
    <section aria-labelledby="eco-glance" className="mt-6">
      <h3 id="eco-glance" className="text-sm font-semibold text-ink">
        Changes side by side
      </h3>
      <p className="mt-0.5 text-xs text-ink-3">
        12 months to {month(e.window.event)}, and from the mean of the 12 months before the episode ({month(e.window.baseline_start)}–
        {month(e.window.baseline_end)}) to {e.window.peak ? month(e.window.peak) : "the peak"}. Percentage changes, not levels: benchmark and local
        units, grades and places differ.
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm" data-testid="economic-glance">
          <caption className="sr-only">Changes in the local price, consumer prices, the exchange rate and international benchmarks</caption>
          <thead>
            <tr className="border-b border-line text-xs text-ink-3">
              <th scope="col" className="py-1.5 pr-3 font-medium">Series</th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">12-month change</th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">Baseline to peak</th>
              <th scope="col" className="py-1.5 pl-3 font-medium">Data in the window</th>
            </tr>
          </thead>
          <tbody>
            {rs.map((r) => (
              <tr key={r.key} className="border-b border-line/60 align-top">
                <th scope="row" className="py-1.5 pr-3 font-normal text-ink">
                  {r.label}
                  {r.detail && <span className="block text-xs text-ink-3">{r.detail}</span>}
                </th>
                {r.state === "ok" ? (
                  <>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.yoy == null ? <Missing why={r.yoyReason} /> : signedPct(r.yoy)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.peak == null ? <Missing why={r.peakReason} /> : signedPct(r.peak)}</td>
                    <td className="py-1.5 pl-3 text-xs text-ink-2">{coverageText(r.coverage)}</td>
                  </>
                ) : (
                  <td colSpan={3} className="px-3 py-1.5 text-ink-2" data-testid={`economic-missing-${r.key}`}>
                    <Tag tone="muted">{stateLabel(r.state)}</Tag> <span className="text-xs">{r.reason}</span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {e.relative_changes.some((r) => r.status === "ok") && (
        <ul className="mt-3 space-y-1 text-sm text-ink-2" data-testid="economic-relative">
          {e.relative_changes.map((r) =>
            r.status === "ok" ? (
              <li key={r.key + r.horizon}>
                {r.label} ({r.horizon}): the price changed {signedPct(r.nominal_pct)} against {signedPct(r.deflator_pct)} for {r.key.includes("food") ? "food" : "all-items"}{" "}
                consumer prices, a relative change of <strong className="text-ink">{signedPct(r.relative_pct)}</strong>.
              </li>
            ) : r.horizon.startsWith("12") ? (
              <li key={r.key + r.horizon} className="text-ink-3">
                {r.label} cannot be computed: {r.reason}.
              </li>
            ) : null,
          )}
          <li className="text-xs text-ink-3">A relative change compares the price with the national average basket; it is not a change in any household’s purchasing power.</li>
        </ul>
      )}
    </section>
  );
}

const Missing = ({ why }: { why?: string | null }) => (
  <span className="text-ink-3">
    not available
    {why && <span className="block text-xs">{why}</span>}
  </span>
);

function coverageText(c: Indicator["coverage"]): string {
  if (!c) return "";
  const t = `${c.months_observed_in_window} of ${c.months_in_window} months`;
  return c.months_missing_in_window > 0 ? `${t}; ${c.months_missing_in_window} missing` : t;
}

/* --- charts ------------------------------------------------------------------------------------------- */

type Line = { name: string; data: (number | null)[]; color: string; dash?: "solid" | "dashed" | "dotted"; width?: number; opacity?: number };

const sentence = (t: string): string => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

function lineOption(p: Palette, e: EconomicAvailable, lines: Line[], yName: string) {
  const base = baseOption(p);
  const months = e.charts.months;
  const at = (m: string) => (months.includes(m) ? m : undefined);
  const event = at(e.charts.event);
  const bs = at(e.charts.baseline.start) ?? months[0];
  const be = at(e.charts.baseline.end);
  const fmt = (v: unknown) => (typeof v === "number" ? v.toFixed(1) : "not available");
  return {
    ...base,
    grid: { left: 56, right: 20, top: 30, bottom: 36 },
    legend: { show: false }, // an HTML legend above the chart wraps cleanly on a phone (see LegendKey)
    xAxis: { ...(base.xAxis as object), type: "category", data: months, boundaryGap: false },
    yAxis: { ...(base.yAxis as object), type: "value", scale: true, name: yName, nameGap: 14 },
    tooltip: { ...(base.tooltip as object), valueFormatter: fmt },
    series: lines.map((l, i) => ({
      type: "line",
      name: l.name,
      data: l.data,
      connectNulls: false,
      showSymbol: false,
      lineStyle: { color: l.color, width: l.width ?? 1.8, type: l.dash ?? "solid", opacity: l.opacity ?? 1 },
      itemStyle: { color: l.color },
      ...(i === 0
        ? {
            markArea: be ? { silent: true, itemStyle: { color: p.rainSoft, opacity: 0.5 }, data: [[{ xAxis: bs }, { xAxis: be }]] } : undefined,
            markLine: event
              ? { silent: true, symbol: "none", lineStyle: { color: p.warn, type: "dashed" }, label: { formatter: "investigated", color: p.ink3, fontSize: 11 }, data: [{ xAxis: event }] }
              : undefined,
          }
        : {}),
    })),
  };
}

function Charts({ d, e }: { d: Investigation; e: EconomicAvailable }) {
  const p = usePalette();
  const price = useMemo<Line | null>(
    () => (p ? { name: `Local price (${d.subject.currency})`, data: e.price.chart_index ?? [], color: p.ink, width: 2.4 } : null),
    [p, e.price.chart_index, d.subject.currency],
  );
  const cpi = e.inflation.headline;
  const food = e.inflation.food;
  const fx = e.exchange_rate.period_average;
  const fxOn = e.exchange_rate.applicability === "applies" && fx.state === "ok";
  const bench = e.international.items.filter((b) => b.state === "ok");
  const [showUsd, setShowUsd] = useState(false);

  const cpiLines = useMemo<Line[] | null>(() => {
    if (!p || !price || cpi.state !== "ok") return null;
    const l: Line[] = [price, { name: "Consumer prices, all items", data: cpi.chart_index ?? [], color: p.rain }];
    if (food.state === "ok") l.push({ name: "Consumer prices, food", data: food.chart_index ?? [], color: p.grain, dash: "dashed" });
    return l;
  }, [p, price, cpi, food]);
  const fxLines = useMemo<Line[] | null>(() => {
    if (!p || !price || !fxOn) return null;
    return [price, { name: `${e.exchange_rate.price_currency} per US dollar`, data: fx.chart_index ?? [], color: p.heat, dash: "dotted", width: 2 }];
  }, [p, price, fxOn, fx, e.exchange_rate.price_currency]);
  const benchLines = useMemo<Line[] | null>(() => {
    if (!p || !price || bench.length === 0) return null;
    // Colour and dash pattern both identify a benchmark, so the lines stay distinguishable without colour.
    const shades = [p.rain, p.grain, p.heat];
    const dashes = ["solid", "dashed", "dotted"] as const;
    const l: Line[] = [price];
    bench.forEach((b, i) => {
      const local = b.local_currency?.chart_index;
      const style = { color: shades[i % 3], dash: dashes[i % 3] };
      if (local) l.push({ name: `${shortLabel(b)} (in ${d.subject.currency})`, data: local, ...style });
      if (showUsd || !local) l.push({ name: `${shortLabel(b)} (US dollars)`, data: b.chart_index ?? [], ...style, width: 1.1, opacity: 0.55 });
    });
    return l;
    // `bench` is derived from e.international.items, which is what the memo depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, price, e.international.items, showUsd, d.subject.currency]);

  return (
    <div className="mt-8 space-y-8" data-testid="economic-charts">
      <ChartBlock
        id="eco-cpi"
        title="The price and consumer prices"
        lines={cpiLines}
        e={e}
        empty={`No usable consumer price index: ${cpi.reason ?? stateLabel(cpi.state)}.`}
        caption="Both are indexed to 100 at their own mean over the pre-episode baseline (shaded), so they start level and only their changes are compared. Food consumer prices appear only when the IMF publishes them for this country."
        missing={[
          ["Consumer prices, all items", missingMonths(cpi.chart_index)],
          ["Consumer prices, food", food.state === "ok" ? missingMonths(food.chart_index) : 0],
        ]}
      />
      <ChartBlock
        id="eco-fx"
        title="The price and the exchange rate"
        lines={fxLines}
        e={e}
        empty={`No exchange-rate comparison: ${applicabilityText(e.exchange_rate.applicability)}${fx.state !== "ok" && fx.reason ? ` (${fx.reason})` : ""}.`}
        caption={`Quote: ${e.exchange_rate.quote}. Official period-average rate; households and traders may have faced a different one. A rising line is a weaker local currency against the dollar.`}
        missing={[["Exchange rate", missingMonths(fx.chart_index)]]}
      />
      <ChartBlock
        id="eco-bench"
        title="The price and international benchmarks"
        lines={benchLines}
        e={e}
        empty={e.international.reason ?? "No international benchmark is mapped to this commodity, so no international comparison is made."}
        caption={`${e.international.confidence_text ?? ""} ${e.international.unit_note ?? ""}`.trim()}
        missing={bench.map((b) => [shortLabel(b), missingMonths(b.chart_index)] as [string, number])}
        extra={
          bench.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-ink-2 print:hidden">
              <input type="checkbox" checked={showUsd} onChange={(x) => setShowUsd(x.target.checked)} /> also show US-dollar benchmark prices
            </label>
          )
        }
      />
      {e.international.limitations && e.international.limitations.length > 0 && bench.length > 0 && (
        <details className="text-sm text-ink-2" data-testid="economic-benchmark-limits">
          <summary className="cursor-pointer">Why a benchmark is not the imported price</summary>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {e.international.limitations.map((x) => (
              <li key={x}>{x}</li>
            ))}
            <li>
              Mapping confidence: <strong>{e.international.confidence}</strong>
              {e.international.role ? ` (${e.international.role})` : ""}. {bench.map((b) => b.definition?.text).filter(Boolean).join(" ")}
            </li>
          </ul>
        </details>
      )}
    </div>
  );
}

/** Colour, dash pattern and weight of each line, so the chart can be read without relying on colour alone. */
function LegendKey({ lines }: { lines: Line[] }) {
  const dash = { solid: undefined, dashed: "6 3", dotted: "1.5 3" } as const;
  return (
    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-hidden data-testid="chart-legend">
      {lines.map((l) => (
        <li key={l.name} className="flex items-center gap-1.5">
          <svg width="26" height="8" viewBox="0 0 26 8" role="presentation">
            <line x1="1" y1="4" x2="25" y2="4" stroke={l.color} strokeWidth={l.width ?? 1.8} strokeDasharray={dash[l.dash ?? "solid"]} strokeLinecap="round" opacity={l.opacity ?? 1} />
          </svg>
          {l.name}
        </li>
      ))}
    </ul>
  );
}

function shortLabel(b: Benchmark): string {
  return b.label.replace(/, white, milled$/, "").replace(/, milled$/, "");
}

function ChartBlock({
  id,
  title,
  lines,
  e,
  empty,
  caption,
  missing,
  extra,
}: {
  id: string;
  title: string;
  lines: Line[] | null;
  e: EconomicAvailable;
  empty: string;
  caption: string;
  missing: [string, number][];
  extra?: React.ReactNode;
}) {
  const p = usePalette();
  const ref = useRef<ChartHandle>(null);
  const option = useMemo(() => (p && lines ? lineOption(p, e, lines, "index, 100 = baseline mean") : null), [p, lines, e]);
  const gaps = missing.filter(([, n]) => n > 0);
  return (
    <section aria-labelledby={id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={id} className="text-sm font-semibold text-ink">
          {title}
        </h3>
        <div className="flex items-center gap-3">
          {extra}
          {lines && (
            <button
              type="button"
              onClick={() => ref.current?.downloadPng(`${id}.png`)}
              className="inline-flex h-8 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2 print:hidden"
            >
              <Download className="h-3.5 w-3.5" aria-hidden /> PNG
            </button>
          )}
        </div>
      </div>
      {lines ? (
        <>
          <LegendKey lines={lines} />
          <Chart ref={ref} option={option} height={280} ariaLabel={`${title}, indexed to 100 at the pre-episode baseline mean, ${month(e.window.start)} to ${month(e.window.end)}`} />
          <p className="mt-1 text-xs text-ink-3">{caption}</p>
          {gaps.length > 0 && (
            <p className="mt-1 text-xs text-ink-3" data-testid={`${id}-gaps`}>
              Gaps in the lines are months with no value, not zero: {gaps.map(([n, k]) => `${n} (${k})`).join("; ")}.
            </p>
          )}
        </>
      ) : (
        <p className="mt-1 rounded border border-dashed border-line p-3 text-sm text-ink-2" data-testid={`${id}-empty`}>
          {empty}
        </p>
      )}
    </section>
  );
}

/* --- propositions, lags, gaps, lineage ---------------------------------------------------------------- */

function Propositions({ ev }: { ev: EconomicEvidence }) {
  return (
    <div className="mt-8 grid gap-6 md:grid-cols-2">
      <section aria-labelledby="eco-props" className="md:col-span-2">
        <h3 id="eco-props" className="text-sm font-semibold text-ink">
          What the figures can be set beside
        </h3>
        <p className="mt-0.5 text-xs text-ink-3">
          Each statement is a proposition the figures are compared with, by a fixed rule on the share of the price’s change that another series’ change
          matches. A match is not an explanation.
        </p>
        <ul className="mt-2 divide-y divide-line rounded border border-line" data-testid="economic-propositions">
          {ev.propositions.map((x) => (
            <li key={x.proposition} className="p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-ink">{x.proposition}</span>
                <Tag tone={VERDICT_TONE[x.status] ?? "muted"}>{x.verdict}</Tag>
              </div>
              <p className="mt-0.5 text-sm text-ink-2">{x.basis}.</p>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="eco-notest">
        <h3 id="eco-notest" className="text-sm font-semibold text-ink">
          What this context does not establish
        </h3>
        <ul className="mt-2 space-y-2">
          {ev.causal.map((x) => (
            <li key={x.text} className="flex flex-col gap-1 text-sm text-ink sm:flex-row sm:gap-3">
              <span className="shrink-0 sm:w-24">
                <Tag tone={INFERENCE_TONE[x.inference] ?? "muted"}>{x.inference}</Tag>
              </span>
              <span>{x.text}</span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="eco-unres">
        <h3 id="eco-unres" className="text-sm font-semibold text-ink">
          Alternatives the data cannot separate
        </h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
          {ev.unresolved.map((x) => (
            <li key={x.text}>{x.text}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Lags({ e }: { e: EconomicAvailable }) {
  if (e.lags.pairs.length === 0) return null;
  return (
    <details className="mt-6 text-sm" data-testid="economic-lags">
      <summary className="cursor-pointer font-semibold text-ink">Timing: descriptive lag comparisons</summary>
      <p className="mt-1 text-ink-2">{e.lags.caution}</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[30rem] text-left text-xs">
          <caption className="sr-only">Rank correlation of monthly changes at lags of 0 to 6 months</caption>
          <thead>
            <tr className="border-b border-line text-ink-3">
              <th scope="col" className="py-1 pr-3 font-medium">Compared with</th>
              {e.lags.lags_months.map((l) => (
                <th key={l} scope="col" className="px-2 py-1 text-right font-medium">{l} mo</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {e.lags.pairs.map((pr) => (
              <tr key={pr.key} className="border-b border-line/60">
                <th scope="row" className="py-1 pr-3 font-normal text-ink">{pr.label}</th>
                {e.lags.lags_months.map((l) => {
                  const r = pr.rows.find((x) => x.lag === l);
                  return (
                    <td key={l} className="px-2 py-1 text-right tabular-nums text-ink-2">
                      {r && r.status === "ok" && r.spearman != null ? `${r.spearman > 0 ? "+" : ""}${r.spearman.toFixed(2)}` : "n/a"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-ink-3">{e.lags.method}. “n/a” means too few overlapping months.</p>
    </details>
  );
}

function Gaps({ e, ev }: { e: EconomicAvailable; ev: EconomicEvidence | undefined }) {
  const gaps = ev?.gaps ?? e.missing.map((m) => `${m.label}: ${m.reason}`);
  if (gaps.length === 0) return null;
  return (
    <section aria-labelledby="eco-gaps" className="mt-6">
      <h3 id="eco-gaps" className="text-sm font-semibold text-ink">
        Missing or not integrated
      </h3>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink-2" data-testid="economic-gaps">
        {gaps.map((g) => (
          <li key={g}>{g}</li>
        ))}
      </ul>
    </section>
  );
}

function Lineage({ e }: { e: EconomicAvailable }) {
  return (
    <details className="mt-6 text-sm" data-testid="economic-lineage">
      <summary className="cursor-pointer font-semibold text-ink">Sources, vintages and hashes</summary>
      <ul className="mt-2 space-y-2 text-xs text-ink-2">
        {e.lineage.map((l) => (
          <li key={l.series_key}>
            <span className="font-medium text-ink">{l.label}</span> — {l.provider === "imf" ? "IMF" : "World Bank"} <code>{l.source_ref}</code>
            <br />
            {l.first_period ? `${month(l.first_period)} to ${month(l.last_period ?? l.first_period)}; ` : "no observations; "}
            published {l.vintage_publication_date?.slice(0, 10) ?? "date not recorded"}, retrieved {l.retrieved_at?.slice(0, 10) ?? "—"}; observations SHA-256{" "}
            <code>{l.observations_sha256 ? l.observations_sha256.slice(0, 16) : "none"}</code>; licence {l.licence}.
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-3">{Object.values(e.transformations).join(" ")}</p>
    </details>
  );
}
