"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { baseOption, Chart, type ChartHandle, usePalette } from "@/components/chart";
import { CopyButton, LinkButton, MONTH_SHORT, MovementTag, signedPct, z1 } from "@/components/market-bits";
import { Empty, ErrorState, Field, Loading, Note, PageHeader, Panel, Select, Stat, Tag } from "@/components/ui";
import { TierTag } from "@/app/explorer/explorer-client";
import { fmt, month, pct } from "@/lib/format";
import { exportUrl, useGlobalDetail, useObservations, type GlobalDetail } from "@/lib/global-api";
import {
  historyCsvUrl,
  useBrief,
  useEnvironment,
  useHistory,
  useMovement,
  useSeasonality,
  useSeriesDetail,
  type Assessment,
  type Environment,
  type History,
  type Movement,
  type Seasonality,
} from "@/lib/market-api";
import { useUrlState } from "@/lib/url-state";

const RANGES = [
  { value: "all", label: "All months" },
  { value: "60", label: "Last 5 years" },
  { value: "36", label: "Last 3 years" },
  { value: "12", label: "Last 12 months" },
];

const SECTION_TITLE: Record<string, string> = {
  latest: "Latest observation",
  what_changed: "What changed",
  unusualness: "Is it unusual?",
  data: "How complete are the data?",
  environment: "Environmental context",
  forecast: "Forecast",
  uncertainty: "What to keep in mind",
};

function PriceHistory({ history, movement, range, chartRef }: { history: History; movement?: Movement; range: string; chartRef: React.Ref<ChartHandle> }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const items = range === "all" ? history.items : history.items.slice(-Number(range));
    const first = items[0]?.period;
    const marks = (movement?.history ?? [])
      .filter((h) => !first || h.period >= first)
      .map((h) => {
        const hit = items.find((d) => d.period === h.period);
        return hit?.price != null ? { coord: [hit.period, hit.price], name: `${h.label.replace(/_/g, " ")}: ${signedPct(h.pct_change)}` } : null;
      })
      .filter(Boolean);
    const b = baseOption(p);
    return {
      ...b,
      grid: { ...(b.grid as object), bottom: 62 },
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number | null) => (v == null ? "no observation" : `${fmt(v)} ${history.currency}/${history.unit}`) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", scale: true, name: `${history.currency} per ${history.unit}` },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, borderColor: p.line, textStyle: { color: p.ink3 } }],
      series: [
        {
          name: "Price",
          type: "line",
          showSymbol: items.length < 40,
          symbolSize: 4,
          connectNulls: false,
          lineStyle: { color: p.grain, width: 2 },
          itemStyle: { color: p.grain },
          data: items.map((d) => [d.period, d.price]),
          markPoint: marks.length ? { symbol: "circle", symbolSize: 10, label: { show: false }, itemStyle: { color: p.surface, borderColor: p.bad, borderWidth: 2 }, data: marks } : undefined,
        },
      ],
    };
  }, [p, history, movement, range]);
  return <Chart ref={chartRef} option={option} height={330} ariaLabel="Monthly price history" />;
}

function SeasonalChart({ data }: { data: Seasonality }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p || data.status !== "ok") return null;
    const b = baseOption(p);
    const cur = (v: number) => (v - 1) * 100;
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}% vs the year's average` },
      xAxis: { ...(b.xAxis as object), type: "category", data: data.months.map((m) => m.name) },
      yAxis: { ...(b.yAxis as object), type: "value", name: "% vs year average", axisLabel: { color: p.ink3, formatter: "{value}%" } },
      series: [
        { name: "Typical range (middle half of years)", type: "bar", stack: "iqr", silent: true, itemStyle: { color: "transparent" }, data: data.months.map((m) => cur(m.q25)), barWidth: "55%" },
        { name: "Typical range (middle half of years)", type: "bar", stack: "iqr", itemStyle: { color: p.grainSoft }, data: data.months.map((m) => cur(m.q75) - cur(m.q25)), barWidth: "55%", tooltip: { show: false } },
        { name: "Median", type: "line", data: data.months.map((m) => cur(m.median_index)), lineStyle: { color: p.grain, width: 2 }, itemStyle: { color: p.grain }, symbolSize: 5 },
      ],
      legend: { show: false },
    };
  }, [p, data]);
  return <Chart option={option} height={240} ariaLabel="Typical seasonal price pattern by calendar month" />;
}

function EnvironmentChart({ env, history }: { env: Environment; history?: History }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const b = baseOption(p);
    const wx = env.market_cell_series;
    const start = wx[0]?.period ?? env.production_region_series[0]?.period;
    const prices = (history?.items ?? []).filter((d) => !start || d.period >= start);
    return {
      ...b,
      grid: { ...(b.grid as object), right: 60, bottom: 40 },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: [
        { ...(b.yAxis as object), type: "value", name: "anomaly (s.d.)", min: -4, max: 4 },
        { ...(b.yAxis as object), type: "value", scale: true, name: history ? `${history.currency}/${history.unit}` : "", splitLine: { show: false } },
      ],
      series: [
        { name: "Rainfall anomaly, market cell", type: "bar", data: wx.map((d) => [d.period, d.rain_anomaly_z]), itemStyle: { color: p.rainSoft, borderColor: p.rain, borderWidth: 0.5 }, barMaxWidth: 5 },
        ...(env.production_region_series.length
          ? [{ name: "Season rainfall anomaly, production region", type: "line", step: "end", showSymbol: false, data: env.production_region_series.map((d) => [d.period, d.season_rain_anomaly_z]), lineStyle: { color: p.rain, width: 2 }, itemStyle: { color: p.rain } }]
          : []),
        { name: "Price", type: "line", yAxisIndex: 1, showSymbol: false, connectNulls: false, data: prices.map((d) => [d.period, d.price]), lineStyle: { color: p.grain, width: 1.5 }, itemStyle: { color: p.grain } },
      ],
    };
  }, [p, env, history]);
  return <Chart option={option} height={300} ariaLabel="Weather anomalies and prices over time" />;
}

function MovementCard({ a, peers }: { a: Assessment; peers: Movement["peers"] }) {
  if (a.status !== "ok" || !a.overall) {
    return <Empty>{a.warnings?.[0] ?? "There is not enough history to assess the latest movement."}</Empty>;
  }
  const o = a.overall;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-2xl font-medium text-ink">{signedPct(a.pct_change)}</span>
        <MovementTag label={a.label} />
        {!a.stable && a.label !== "insufficient_history" && <Tag tone="warn">short history</Tag>}
      </div>
      <p className="text-sm text-ink-2">
        {month(a.reference_period)} to {month(a.period)}
        {a.span_months && a.span_months > 1 ? ` (${a.span_months} months; intermediate months missing)` : ""}: {fmt(a.reference_price)} to {fmt(a.price)}.
      </p>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Larger than" value={o.percentile_of_size == null ? "—" : pct(o.percentile_of_size)} hint={`of ${o.n_reference} earlier changes`} />
        <Stat label="Robust z-score" value={z1(o.robust_z)} hint="median / MAD scale" />
        <Stat
          label="Same month, earlier years"
          value={a.seasonal?.percentile_of_size == null ? "—" : pct(a.seasonal.percentile_of_size)}
          hint={a.seasonal ? `${a.seasonal.n_reference} years, ${MONTH_SHORT[a.seasonal.calendar_month - 1]}` : "fewer than 5 years"}
        />
        <Stat label="12-month change" value={a.year_on_year ? signedPct(a.year_on_year.pct_change) : "—"} hint={a.year_on_year ? a.year_on_year.label.replace(/_/g, " ") : "no price a year earlier"} />
      </dl>
      {peers?.status === "ok" && (
        <p className="text-sm text-ink-2">
          Other markets, same commodity and country: {pct(peers.share_same_direction)} of {peers.n_peers} moved in the same direction (median change{" "}
          {signedPct(peers.peer_median_pct_change)}).{" "}
          {peers.pattern === "shared" && "The movement was shared across markets."}
          {peers.pattern === "isolated" && "The movement was not shared by most other markets."}
          {peers.pattern === "isolated_reversing" && "It was not shared and reversed the next month, which can indicate a reporting anomaly rather than a market movement."}
        </p>
      )}
      {a.volatility && a.volatility.label === "elevated" && (
        <p className="text-sm text-ink-2">
          Month-to-month variability over the last {a.volatility.window_months} months is higher than in {pct(a.volatility.percentile)} of earlier periods.
        </p>
      )}
      {(a.warnings ?? []).map((w) => (
        <Note key={w} tone="warn">
          {w.charAt(0).toUpperCase() + w.slice(1)}.
        </Note>
      ))}
      <details className="text-sm text-ink-3">
        <summary className="cursor-pointer text-ink-2">Method</summary>
        <p className="mt-2">{a.method}</p>
        <p className="mt-2">
          Labels by percentile of size: below 80% typical, 80–95% larger than usual, 95–99% unusual, 99% and above exceptional. At least 24 earlier
          comparable changes are required; fewer than 48 is marked as a short history. Only changes that ended before the assessed month are used.
        </p>
      </details>
    </div>
  );
}


const OBS_PAGE = 24;

const FLAG_TEXT: Record<string, string> = {
  invalid_price: "price not a valid positive number",
  duplicate_conflict: "conflicts with another record for the same month",
  missing_price: "no price reported",
};

function Observations({ id, currency, unit }: { id: string; currency: string; unit: string }) {
  const [offset, setOffset] = useState(0);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const win = { start: /^\d{4}-\d{2}$/.test(start) ? start : undefined, end: /^\d{4}-\d{2}$/.test(end) ? end : undefined };
  const obs = useObservations(id, { limit: OBS_PAGE, offset, ...win });
  const total = obs.data?.total ?? 0;
  return (
    <Panel
      title="Stored observations"
      note="Every record stored for this series, newest last, including records that are not used in the price history. The export contains the same records."
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <Field label="From (YYYY-MM)" htmlFor="o-start">
            <input id="o-start" value={start} onChange={(e) => (setStart(e.target.value), setOffset(0))} placeholder="2023-01" inputMode="numeric" className="h-9 w-28 rounded border border-line bg-surface px-2 text-sm text-ink" />
          </Field>
          <Field label="To (YYYY-MM)" htmlFor="o-end">
            <input id="o-end" value={end} onChange={(e) => (setEnd(e.target.value), setOffset(0))} placeholder="2024-12" inputMode="numeric" className="h-9 w-28 rounded border border-line bg-surface px-2 text-sm text-ink" />
          </Field>
          <a href={exportUrl(id, "csv", win.start, win.end)} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2" download>
            <Download className="h-3.5 w-3.5" aria-hidden /> CSV
          </a>
          <a href={exportUrl(id, "json", win.start, win.end)} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2" download>
            <Download className="h-3.5 w-3.5" aria-hidden /> JSON
          </a>
        </div>
      }
    >
      {obs.isLoading && <Loading label="Loading observations" />}
      {obs.isError && <ErrorState error={obs.error} what="the stored observations" />}
      {obs.data && obs.data.items.length === 0 && <Empty>No stored record falls in this period.</Empty>}
      {obs.data && obs.data.items.length > 0 && (
        <>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Stored observations table">
            <table className="w-full min-w-[560px] text-sm" data-testid="observations-table">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th className="py-2 pr-3 font-medium">Month</th>
                  <th className="py-2 pr-3 text-right font-medium">
                    Price ({currency}/{unit})
                  </th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium">Quality flags</th>
                </tr>
              </thead>
              <tbody>
                {obs.data.items.map((o, i) => (
                  <tr key={`${o.period}-${offset + i}`} className="border-b border-line/60 align-top">
                    <td className="whitespace-nowrap py-1.5 pr-3 text-ink">{month(o.period)}</td>
                    <td className="py-1.5 pr-3 text-right text-ink">{o.price == null ? "—" : fmt(o.price)}</td>
                    <td className="py-1.5 pr-3">
                      {o.used_in_series ? <Tag tone="good">used</Tag> : o.valid ? <Tag tone="muted">duplicate, not used</Tag> : <Tag tone="warn">excluded</Tag>}
                    </td>
                    <td className="py-1.5 text-xs text-ink-3">
                      {o.quality_flags.length ? o.quality_flags.map((f) => FLAG_TEXT[f] ?? f.replace(/_/g, " ")).join("; ") : "none"}
                      {o.reference_period_start ? ` · reference ${o.reference_period_start.slice(0, 10)} to ${o.reference_period_end?.slice(0, 10) ?? "?"}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-3">
            <span>
              {offset + 1}–{Math.min(offset + OBS_PAGE, total)} of {total.toLocaleString()} records
            </span>
            <div className="flex gap-2">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - OBS_PAGE))} className="rounded border border-line px-3 py-1 text-ink disabled:opacity-40">
                Previous
              </button>
              <button type="button" disabled={offset + OBS_PAGE >= total} onClick={() => setOffset(offset + OBS_PAGE)} className="rounded border border-line px-3 py-1 text-ink disabled:opacity-40">
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}

function Completeness({ g }: { g: GlobalDetail }) {
  const c = g.completeness;
  const flags = Object.entries(c.quality_flag_counts);
  return (
    <Panel title="Completeness and quality" note="What is stored for this series and what it can support.">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4" data-testid="completeness">
        <Stat label="Months observed" value={`${c.valid_months} of ${c.months_spanned}`} hint={`${pct(c.coverage)} of the months in its span`} />
        <Stat label="Missing months" value={c.missing_months} hint={c.missing_months ? `longest gap ${c.longest_gap_months} months` : "no gaps"} />
        <Stat label="Records stored" value={c.records_stored} hint={`${c.records_not_valid} not valid${c.months_with_duplicate_records ? `, ${c.months_with_duplicate_records} months with duplicates` : ""}`} />
        <Stat label="Coordinates" value={g.series.coordinate_status === "ok" ? "valid" : g.series.coordinate_status} hint={g.series.coordinate_status === "ok" ? undefined : "market is not plotted on maps"} />
      </dl>
      <ul className="mt-4 space-y-1.5 text-sm text-ink-2">
        <li>
          {c.usable ? "Enough history to describe (at least 12 monthly prices)." : "Too short to describe: fewer than 12 monthly prices, so movement assessments are withheld."}
        </li>
        <li>
          {c.eligible
            ? "Meets the completeness rules for forecast evaluation (48 prices, 80% coverage, no gap over 6 months, valid coordinates)."
            : `Does not meet the forecast-evaluation rules: ${c.ineligible_reasons ?? "see coverage"}.`}
        </li>
        {flags.length > 0 && (
          <li>
            Quality flags on stored records:{" "}
            {flags.map(([f, n]) => `${n} × ${(FLAG_TEXT[f] ?? f).replace(/_/g, " ")}`).join("; ")}. Flagged records are kept in the export and left out of the history.
          </li>
        )}
      </ul>
    </Panel>
  );
}

export function MarketClient() {
  const { get, set } = useUrlState();
  const id = get("series") || undefined;
  const range = get("range") || "all";
  const detail = useSeriesDetail(id);
  const global = useGlobalDetail(id);
  const history = useHistory(id);
  const movement = useMovement(id);
  const seasonality = useSeasonality(id);
  const env = useEnvironment(id);
  const brief = useBrief(id);
  const chartRef = useRef<ChartHandle>(null);

  if (!id) {
    return (
      <div>
        <PageHeader title="Market intelligence" lede="Choose a market and commodity to see its price history, how unusual recent movements are, and the data behind it." />
        <Empty>
          No series selected. <Link className="underline" href="/explorer">Open the explorer</Link> and pick a market.
        </Empty>
      </div>
    );
  }
  if (detail.isLoading) return <Loading label="Loading market" />;
  if (detail.isError || !detail.data) return <ErrorState error={detail.error} what="this market series" />;

  const s = detail.data.series;
  const sum = detail.data.summary;
  const prov = detail.data.provenance;
  const stale = (sum.months_behind_dataset ?? 0) >= 3;
  const fc = brief.data?.evidence.forecast;
  const grouped = (brief.data?.sentences ?? []).reduce<Record<string, string[]>>((acc, x) => {
    (acc[x.section] ??= []).push(x.text);
    return acc;
  }, {});

  return (
    <div>
      <PageHeader title={`${s.commodity_name} in ${s.market_name}`} lede={`${[s.admin1_name, detail.data.series.country_iso3].filter(Boolean).join(", ")} · ${s.price_type.toLowerCase()} price, ${s.currency} per ${s.unit}`}>
        <CopyButton label="Copy link" icon="share" text={() => window.location.href} />
        <LinkButton href={`/compare?s=${s.series_id}`}>Compare with other markets</LinkButton>
      </PageHeader>

      {global.data && (
        <p className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-2" data-testid="data-tier">
          <span className="text-ink-3">Country status</span>
          <TierTag status={global.data.country.status} />
          <span>
            {global.data.country.status_note}.
            {brief.data && !fc ? " This series is not itself covered by a forecast evaluation." : ""}
          </span>
          <Link className="underline" href={`/explorer?country=${s.country_iso3}`}>
            More from {global.data.country.name}
          </Link>
        </p>
      )}
      <div className="mb-5 grid grid-cols-2 gap-x-6 gap-y-4 rounded-md border border-line bg-surface p-5 md:grid-cols-5">
        <Stat label="Latest price" value={`${fmt(sum.latest_price)} ${s.currency}`} hint={`per ${s.unit}`} />
        <Stat label="Observed for" value={month(sum.latest_period)} hint={stale ? `${sum.months_behind_dataset} months behind the newest data` : "the month the price describes"} />
        <Stat label="1 month" value={signedPct(sum.changes?.m1?.pct_change)} hint={sum.changes?.m1 ? `from ${month(sum.changes.m1.reference_period)}` : "previous month missing"} />
        <Stat label="12 months" value={signedPct(sum.changes?.m12?.pct_change)} hint={sum.changes?.m12 ? `from ${month(sum.changes.m12.reference_period)}` : "no price a year earlier"} />
        <Stat label="History" value={`${sum.n_observations} months`} hint={`since ${month(sum.first_period)} · ${pct(sum.coverage)} observed`} />
      </div>
      {stale && (
        <div className="mb-5">
          <Note tone="warn">
            This series was last observed for {month(sum.latest_period)}. Newer months exist for other series in the dataset, so it may not reflect current
            conditions.
          </Note>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="grid min-w-0 grid-cols-1 gap-5">
        <Panel
          title="Price history"
          note="Gaps are months with no valid observation; nothing is interpolated. Circled months had an unusual change given the history available at the time."
          actions={
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Range" htmlFor="f-range">
                <Select id="f-range" value={range} onChange={(v) => set({ range: v === "all" ? null : v })} options={RANGES} />
              </Field>
              <button type="button" onClick={() => chartRef.current?.downloadPng(`market_almanac_${s.series_id}.png`)} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
                <Download className="h-3.5 w-3.5" aria-hidden /> PNG
              </button>
              <a href={historyCsvUrl(s.series_id)} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
                <Download className="h-3.5 w-3.5" aria-hidden /> CSV
              </a>
            </div>
          }
        >
          {history.isLoading && <Loading label="Loading prices" />}
          {history.isError && <ErrorState error={history.error} what="price history" />}
          {history.data && <PriceHistory history={history.data} movement={movement.data} range={range} chartRef={chartRef} />}
          {history.data && (
            <p className="mt-2 text-xs text-ink-3">
              {history.data.n_observed} observed months, {history.data.n_missing} missing
              {history.data.excluded_records > 0 ? `, ${history.data.excluded_records} duplicate or invalid records excluded` : ""}.
            </p>
          )}
        </Panel>

        <Panel title="How unusual is the latest movement?" note="Compared with this series' own earlier movements of the same length.">
          {movement.isLoading && <Loading label="Assessing" />}
          {movement.isError && <ErrorState error={movement.error} what="the movement assessment" />}
          {movement.data && <MovementCard a={movement.data.assessment} peers={movement.data.peers} />}
          {movement.data && <p className="mt-4 text-xs text-ink-3">{movement.data.disclaimer}</p>}
        </Panel>
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-5">
        <Panel
          title="Market brief"
          note={brief.data ? `As of ${month(brief.data.as_of_period)} · generated from the statistics on this page` : undefined}
          actions={brief.data && <CopyButton label="Copy brief" text={() => `${brief.data!.title}\n\n${brief.data!.text}\n\nSource: Market Almanac, ${window.location.href}`} />}
        >
          {brief.isLoading && <Loading label="Writing brief" />}
          {brief.isError && <ErrorState error={brief.error} what="the market brief" />}
          {brief.data && (
            <div className="space-y-3" data-testid="market-brief">
              {Object.entries(grouped).map(([section, texts]) => (
                <div key={section}>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{SECTION_TITLE[section] ?? section}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-ink-2">{texts.join(" ")}</p>
                </div>
              ))}
              <p className="border-t border-line pt-2 text-xs text-ink-3">{brief.data.method}</p>
            </div>
          )}
        </Panel>

        <Panel title="Seasonal pattern" note="Each month's price relative to the average of its calendar year, across years.">
          {seasonality.isLoading && <Loading label="Loading" />}
          {seasonality.data?.status === "ok" ? (
            <>
              <SeasonalChart data={seasonality.data} />
              <p className="mt-2 text-sm text-ink-2">
                Prices are typically highest in {MONTH_SHORT[(seasonality.data.peak_month ?? 1) - 1]} and lowest in {MONTH_SHORT[(seasonality.data.trough_month ?? 1) - 1]}, a
                difference of about {pct(seasonality.data.seasonal_amplitude)} ({seasonality.data.years_used} years).
              </p>
            </>
          ) : (
            seasonality.data && <Empty>{seasonality.data.note ?? "Not enough complete years to estimate a seasonal pattern."}</Empty>
          )}
        </Panel>
        </div>
      </div>

      <div className="mt-5">
        <Panel title="Weather context" note="Observed weather shown next to prices. Co-movement here is a correlation, not a demonstrated cause.">
          {env.isLoading && <Loading label="Loading weather" />}
          {env.isError && <ErrorState error={env.error} what="weather context" />}
          {env.data?.status === "ok" ? (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <EnvironmentChart env={env.data} history={history.data} />
              <div className="space-y-4 text-sm text-ink-2">
                {env.data.market_cell && (
                  <div>
                    <h3 className="font-medium text-ink">Near the market</h3>
                    <p className="mt-1">
                      {month(env.data.market_cell.period)}: rainfall anomaly {z1(env.data.market_cell.rain_anomaly_z)}, temperature anomaly {z1(env.data.market_cell.temp_anomaly_z)}{" "}
                      (standard deviations from earlier years).
                    </p>
                    {env.data.market_cell.qc_flagged_months_last_24 > 0 && (
                      <p className="mt-1 text-warn">
                        {env.data.market_cell.qc_flagged_months_last_24} of the last 24 months contain a rainfall value flagged as implausible by quality control; flagged days are
                        treated as missing.
                      </p>
                    )}
                    <p className="mt-1 text-xs text-ink-3">{env.data.market_cell.basis}.</p>
                  </div>
                )}
                {env.data.production_region ? (
                  <div>
                    <h3 className="font-medium text-ink">Where {env.data.production_region.crop} is grown</h3>
                    <p className="mt-1">
                      As of {month(env.data.production_region.period)} ({env.data.production_region.in_season ? "growing season in progress" : `${env.data.production_region.months_since_harvest} months since harvest`}):
                      seasonal rainfall anomaly {z1(env.data.production_region.season_rain_anomaly_z)}, previous season {z1(env.data.production_region.previous_season_rain_anomaly_z)}.
                    </p>
                    <p className="mt-1 text-xs text-ink-3">
                      {env.data.production_region.basis} Season: {env.data.production_region.season_months.map((m) => MONTH_SHORT[m - 1]).join(", ")}
                      {env.data.production_region.calendar_basis === "fallback" ? " (millet calendar used; no national entry for this crop)" : ""}.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-ink-3">No production-region index is defined for this commodity and country.</p>
                )}
                <ul className="list-disc space-y-1 pl-4 text-xs text-ink-3">
                  {env.data.caveats.slice(0, 3).map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            env.data && <Empty>No weather data are stored for this market, so no weather context is shown. Weather is available only for markets in the countries covered by the weather studies.</Empty>
          )}
        </Panel>
      </div>

      {global.data && (
        <div className="mt-5">
          <Completeness g={global.data} />
        </div>
      )}
      <div className="mt-5">
        <Observations id={s.series_id} currency={s.currency} unit={s.unit} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel title="Forecast" note="Forecasts are shown only for series covered by an out-of-sample evaluation.">
          {!fc && (
            <Empty>
              No evaluated forecasting model covers this series, so no forecast is shown.
              {global.data && global.data.country.evaluation_records.length > 0 ? (
                <>
                  {" "}
                  {global.data.country.name} is covered by {global.data.country.evaluation_records.length} published evaluation
                  {global.data.country.evaluation_records.length === 1 ? "" : "s"} of other series.{" "}
                  <Link className="underline" href="/forecastability">
                    Read the Forecastability Atlas
                  </Link>{" "}
                  or the{" "}
                  <Link className="underline" href="/studies">
                    study library
                  </Link>
                  .
                </>
              ) : (
                global.data && " No published study evaluates forecasts for this country."
              )}
            </Empty>
          )}
          {fc && (
            <div className="space-y-2 text-sm text-ink-2">
              <div className="flex flex-wrap items-center gap-2">
                <Tag tone={fc.status === "issued" ? "neutral" : "muted"}>{fc.status === "issued" ? "Forecast available" : "Forecast withheld"}</Tag>
                <Tag tone={fc.validation_status === "validated_outperforms_baseline" ? "good" : "warn"}>
                  {fc.validation_status === "validated_outperforms_baseline" ? "beat its benchmark out of sample" : "no demonstrated skill over the benchmark"}
                </Tag>
              </div>
              <p>
                {fc.status === "issued"
                  ? `A ${fc.horizon}-month statistical forecast for ${month(fc.target_period)} exists, made from information assumed available at the end of ${month(fc.origin_period)}.`
                  : `Withheld: ${fc.reason ?? "the series did not qualify"}.`}
              </p>
              <p>
                <Link className="underline" href={`/forecasts?experiment=${fc.experiment_id}&series=${s.series_id}`}>
                  See the forecast, its interval and its track record
                </Link>
              </p>
            </div>
          )}
        </Panel>

        <Panel title="Data and provenance">
          <dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
            <dt className="text-ink-3">Source</dt>
            <dd className="text-ink-2">{prov.attribution}</dd>
            <dt className="text-ink-3">Observation date</dt>
            <dd className="text-ink-2">{prov.observation_basis}</dd>
            <dt className="text-ink-3">Retrieved</dt>
            <dd className="text-ink-2">{prov.retrieved_at ? new Date(prov.retrieved_at).toUTCString() : "unknown"}</dd>
            <dt className="text-ink-3">Snapshot</dt>
            <dd className="break-all text-ink-2">
              <code className="code">{prov.snapshot_id}</code>
              {global.data?.provenance.snapshot_revision ? ` (${global.data.provenance.snapshot_revision})` : ""}
            </dd>
            {global.data?.provenance.observation_hash && (
              <>
                <dt className="text-ink-3">Observation hash</dt>
                <dd className="break-all text-ink-2">
                  <code className="code">{global.data.provenance.observation_hash}</code>
                </dd>
              </>
            )}
            <dt className="text-ink-3">Source record</dt>
            <dd className="break-all text-ink-2">{prov.source_ref ?? "—"}</dd>
            <dt className="text-ink-3">Series ID</dt>
            <dd className="break-all text-ink-2">
              <code className="code">{s.series_id}</code>
            </dd>
            <dt className="text-ink-3">Forecast evaluation</dt>
            <dd className="text-ink-2">{s.eligible ? "Meets the completeness rules." : `Not eligible: ${s.ineligible_reasons ?? "see data coverage"}.`}</dd>
            <dt className="text-ink-3">Reuse</dt>
            <dd className="text-ink-2">{prov.license_note}</dd>
          </dl>
        </Panel>
      </div>
    </div>
  );
}
