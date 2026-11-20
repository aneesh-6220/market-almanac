"use client";

import { ArrowLeft, Download, FileText, Printer } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { baseOption, Chart, type ChartHandle, type Palette, usePalette } from "@/components/chart";
import { CopyButton, LinkButton, signedPct, z1 } from "@/components/market-bits";
import { cn, Empty, ErrorState, Field, inputClass, Loading, Note, Panel, Tag } from "@/components/ui";
import { loadingLabel } from "@/lib/api";
import { month } from "@/lib/format";
import {
  configParams,
  EXTENT_LABEL,
  exportUrl,
  FLAG_LABEL,
  type InferenceItem,
  type Investigation,
  KIND_LABEL,
  type PeerRow,
  permalink,
  useInvestigation,
  zText,
} from "@/lib/investigation-api";
import { useUrlState } from "@/lib/url-state";

import { EconomicContext } from "./economic-context";

type Tone = "good" | "neutral" | "warn" | "muted";
const tone = (t: string): Tone => (t === "good" || t === "warn" || t === "neutral" ? t : "muted");

const money = (v: number | null | undefined, d: Investigation) =>
  v == null ? "—" : `${v.toLocaleString("en", { maximumFractionDigits: v < 10 ? 2 : 0 })} ${d.subject.currency}/${d.subject.unit}`;

const SECTIONS = [
  ["glance", "At a glance"],
  ["history", "Price history"],
  ["own", "Against its own past"],
  ["peers", "Comparable markets"],
  ["breadth", "Other foods"],
  ["context", "Context"],
  ["economic", "Economic context"],
  ["evidence", "Evidence"],
  ["method", "Method and export"],
] as const;

export function InvestigationView({ seriesId }: { seriesId: string }) {
  const { get, set } = useUrlState();
  const params = {
    event: get("event") || undefined,
    start: get("start") || undefined,
    end: get("end") || undefined,
    snapshot: get("snapshot") || undefined,
    context: get("context") || undefined,
    as_of: get("as_of") || undefined,
  };
  const q = useInvestigation(seriesId, params);

  return (
    <div>
      <Link href="/investigate" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink print:hidden">
        <ArrowLeft className="h-4 w-4" aria-hidden /> All price movements
      </Link>
      {q.isPending ? (
        <Loading label={loadingLabel(q, "Assembling the investigation")} />
      ) : q.isError ? (
        <div className="space-y-4">
          <ErrorState error={q.error} what="this investigation" />
          {params.snapshot && (
            <button type="button" className="mr-4 text-sm text-rain underline" onClick={() => set({ snapshot: null })}>
              Open it with the data now served (the numbers may differ)
            </button>
          )}
          {params.context && (
            <button type="button" className="mr-4 text-sm text-rain underline" onClick={() => set({ context: null })}>
              Open it with the economic context now served (the context numbers may differ)
            </button>
          )}
          {(params.event || params.start || params.end) && (
            <button type="button" className="text-sm text-rain underline" onClick={() => set({ event: null, start: null, end: null, snapshot: null, context: null, as_of: null })}>
              Use the default month and window instead
            </button>
          )}
        </div>
      ) : (
        <Document
          d={q.data}
          onConfig={(p) => set({ ...p, snapshot: null, context: null })}
          onAsOf={(m) => set({ as_of: m, context: null })}
          asOf={params.as_of}
          refreshing={q.isFetching}
          pinned={!!params.snapshot}
        />
      )}
    </div>
  );
}

function Document({
  d,
  onConfig,
  onAsOf,
  asOf,
  refreshing,
  pinned,
}: {
  d: Investigation;
  onConfig: (p: Record<string, string | null>) => void;
  onAsOf: (m: string | null) => void;
  asOf: string | undefined;
  refreshing: boolean;
  pinned: boolean;
}) {
  const s = d.subject;
  const ep = d.episode;
  return (
    <article className={cn("space-y-6", refreshing && "opacity-70")}>
      <header className="border-b border-line pb-6">
        <p className="text-sm text-ink-3">
          {[s.market_name, s.admin2_name, s.admin1_name, s.country_name].filter(Boolean).join(", ")}
        </p>
        <h1 className="mt-1 font-serif text-3xl leading-tight text-ink md:text-4xl">
          {s.commodity_name} in {s.market_name}, {month(d.config.event)}
        </h1>
        <p className="mt-3 max-w-3xl text-lg text-ink-2">{d.question}</p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          <Tag>{s.price_type} price</Tag>
          <Tag>
            {s.currency} per {s.unit}
          </Tag>
          <Tag>
            {month(s.first_period)} – {month(s.last_period)}, {s.n_observations} months
          </Tag>
          {ep && <Tag tone={KIND_LABEL[ep.kind]?.tone ?? "muted"}>{KIND_LABEL[ep.kind]?.text ?? ep.kind}</Tag>}
          {ep?.data_concern && <Tag tone="warn">Possible recording or unit error</Tag>}
        </div>
        <ConfigBar key={d.config_id} d={d} onConfig={onConfig} />
        <p className="mt-2 max-w-3xl text-xs text-ink-3" data-testid="snapshot-note">
          {pinned ? (
            <>
              This page was opened from a link pinned to price snapshot <code>{d.config.snapshot_id}</code>, which is the snapshot served now.
            </>
          ) : (
            <>
              This address is a <strong>live link</strong>: it loads whatever data the site serves when it is opened, currently price snapshot{" "}
              <code>{d.config.snapshot_id}</code>, and could show different numbers after a data revision.
            </>
          )}{" "}
          “Copy permalink” pins the snapshot: only the newest snapshot of each country is installed, so a pinned link reports a mismatch
          instead of showing different data. Exports always record the snapshot.
        </p>
      </header>

      <nav aria-label="Sections" className="flex flex-wrap gap-x-4 gap-y-1 text-sm print:hidden">
        {SECTIONS.map(([id, label], i) => (
          <a key={id} href={`#${id}`} className="text-ink-2 hover:text-ink">
            <span className="text-ink-3">{i + 1}.</span> {label}
          </a>
        ))}
      </nav>

      <Glance d={d} />
      <History d={d} />
      <OwnPast d={d} />
      <Peers d={d} />
      <Breadth d={d} />
      <Context d={d} />
      <EconomicContext d={d} asOf={asOf} onAsOf={onAsOf} />
      <Evidence d={d} />
      <Method d={d} />
    </article>
  );
}

/* --- configuration ----------------------------------------------------------------------------------- */

function ConfigBar({ d, onConfig }: { d: Investigation; onConfig: (p: Record<string, string | null>) => void }) {
  const p = configParams(d);
  const [event, setEvent] = useState(p.event);
  const [start, setStart] = useState(p.start);
  const [end, setEnd] = useState(p.end);
  const others = d.episodes_in_window.filter((e) => e.peak.slice(0, 7) !== p.event && !e.data_concern);
  return (
    <div className="mt-5 space-y-3 print:hidden">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          onConfig({ event, start, end });
        }}
      >
        <Field label="Month investigated" htmlFor="c-event">
          <input id="c-event" type="month" required className={inputClass} value={event} onChange={(e) => setEvent(e.target.value)} />
        </Field>
        <Field label="Window from" htmlFor="c-start">
          <input id="c-start" type="month" className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field label="Window to" htmlFor="c-end">
          <input id="c-end" type="month" className={inputClass} value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
        <button type="submit" className="h-9 rounded bg-ink px-3 text-sm font-medium text-bg hover:bg-ink-2">
          Update
        </button>
        <CopyButton label="Copy permalink" icon="share" text={() => permalink(window.location.origin, d, true)} />
      </form>
      {others.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-ink-3">Other episodes in this window:</span>
          {others.map((e) => (
            <button
              key={`${e.kind}-${e.start}`}
              type="button"
              onClick={() => onConfig({ event: e.peak.slice(0, 7), start: null, end: null })}
              className="rounded border border-line px-2 py-0.5 text-xs text-ink hover:bg-surface-2"
            >
              {e.direction === "up" ? "Rise" : "Fall"} peaking {month(e.peak)} ({KIND_LABEL[e.kind]?.text.toLowerCase() ?? e.kind})
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- 1. at a glance ---------------------------------------------------------------------------------- */

function Glance({ d }: { d: Investigation }) {
  const toneBorder: Record<Tone, string> = { warn: "border-l-warn", good: "border-l-good", neutral: "border-l-neutral", muted: "border-l-line" };
  return (
    <Panel id="glance" title="1. At a glance">
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {d.evidence.assessment.map((a) => (
          <li key={a.key} className={cn("rounded border border-line border-l-4 bg-surface p-3", toneBorder[tone(a.tone)])}>
            <div className="text-xs text-ink-3">{a.label}</div>
            <div className="mt-0.5 text-lg font-medium text-ink">{a.value}</div>
            {a.detail && <div className="text-xs text-ink-2">{a.detail}</div>}
          </li>
        ))}
      </ul>
      <div className="mt-5 max-w-4xl">
        <h3 className="text-sm font-semibold text-ink">Summary</h3>
        <p className="mt-1 text-ink">{d.evidence.conclusion.text}</p>
        <p className="mt-1 text-xs text-ink-3">Inference: {d.evidence.conclusion.inference}.</p>
      </div>
    </Panel>
  );
}

/* --- 2. price history and observations --------------------------------------------------------------- */

function clampToPeriods(periods: string[], m: string): string {
  if (!periods.length) return m;
  if (m < periods[0]) return periods[0];
  if (m > periods[periods.length - 1]) return periods[periods.length - 1];
  return m;
}

function History({ d }: { d: Investigation }) {
  const p = usePalette();
  const chart = useRef<ChartHandle>(null);
  const oq = d.observation_quality;
  const option = useMemo(() => (p ? priceOption(p, d) : null), [p, d]);
  return (
    <Panel
      id="history"
      title="2. Price history and observation quality"
      note={`Nominal ${d.subject.currency} per ${d.subject.unit}. Gaps are months with no valid observation; they are not filled.`}
      actions={<PngButton chart={chart} name={`${d.config.series_id}-price.png`} />}
    >
      <Chart ref={chart} option={option} height={300} ariaLabel={`Monthly ${d.subject.commodity_name} price in ${d.subject.market_name}, with the episode shaded`} />
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Def label="Months observed in window" value={`${oq.months_observed} of ${oq.months_in_window}`} />
        <Def label="Longest gap" value={`${oq.longest_gap_months} months`} />
        <Def label="Records not used" value={String(oq.records_not_used)} hint="invalid, duplicate or conflicting" />
        <Def label="Price in the month investigated" value={money(d.magnitude.event_price, d)} />
      </dl>
      {d.episode && d.episode.flags.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-ink">Flags on this episode</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-2">
            {d.episode.flags.map((f) => (
              <li key={f}>{FLAG_LABEL[f] ?? f}</li>
            ))}
          </ul>
        </div>
      )}
      {oq.flagged_records.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink-2">{oq.flagged_records.length} records with quality flags</summary>
          <ul className="mt-2 space-y-0.5 text-ink-2">
            {oq.flagged_records.map((r, i) => (
              <li key={`${r.period}-${i}`}>
                {month(r.period)}: {r.price ?? "—"} — {r.flags.join(", ")}
                {r.used === false && " (not used)"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function priceOption(p: Palette, d: Investigation) {
  const periods = d.signals.map((s) => s.period);
  const ep = d.episode;
  const event = clampToPeriods(periods, d.config.event);
  const area = ep
    ? { silent: true, itemStyle: { color: p.warn, opacity: 0.12 }, data: [[{ xAxis: clampToPeriods(periods, ep.start.slice(0, 7)) }, { xAxis: clampToPeriods(periods, ep.end.slice(0, 7)) }]] }
    : undefined;
  const base = baseOption(p);
  return {
    ...base,
    grid: { left: 64, right: 20, top: 30, bottom: 36 },
    xAxis: { ...(base.xAxis as object), type: "category", data: periods, boundaryGap: false },
    yAxis: { ...(base.yAxis as object), type: "value", scale: true, name: `${d.subject.currency}/${d.subject.unit}` },
    tooltip: { ...(base.tooltip as object), valueFormatter: (v: unknown) => (typeof v === "number" ? v.toLocaleString("en") : "no observation") },
    series: [
      {
        type: "line",
        name: "Price",
        data: d.signals.map((s) => s.price),
        connectNulls: false,
        showSymbol: true,
        symbolSize: 4,
        itemStyle: { color: p.ink },
        lineStyle: { color: p.ink, width: 1.8 },
        markArea: area,
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: p.warn, type: "dashed" },
          label: { formatter: "investigated", color: p.ink3, fontSize: 11 },
          data: [{ xAxis: event }],
        },
      },
    ],
  };
}

/* --- 3. against its own past ------------------------------------------------------------------------- */

function OwnPast({ d }: { d: Investigation }) {
  const p = usePalette();
  const chart = useRef<ChartHandle>(null);
  const season = useRef<ChartHandle>(null);
  const u = d.unusualness;
  const se = d.seasonality;
  const option = useMemo(() => (p ? zOption(p, d) : null), [p, d]);
  const sOption = useMemo(() => (p && se.months?.length ? seasonOption(p, d) : null), [p, d, se.months]);
  return (
    <Panel
      id="own"
      title="3. Compared with this market's own history"
      note="Each bar compares one month's 12-month change with every earlier 12-month change of the same series (robust z-score); beyond ±2 is unusual. The figures below compare the month investigated only with changes before the episode began, so they can differ slightly from its bar."
      actions={<PngButton chart={chart} name={`${d.config.series_id}-unusualness.png`} />}
    >
      <Chart ref={chart} option={option} height={240} ariaLabel="Robust z-score of the 12-month change by month, with thresholds at plus and minus 2" />
      {u.status === "ok" ? (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Def label="12-month change" value={signedPct(d.magnitude.event_yoy_pct)} hint={d.magnitude.large_nominal ? "large in nominal terms" : undefined} />
          <Def label="Robust z-score" value={zText(u.z)} hint={`against ${u.n_reference} earlier changes, ${u.reference_years} years`} />
          <Def label="Rank" value={u.percentile == null ? "—" : `${Math.round(u.percentile * 100)}th percentile`} hint="share of earlier changes below it" />
          <Def
            label="Typical 12-month change"
            value={signedPct(u.reference_median_yoy_pct)}
            hint={`middle 80%: ${signedPct(u.reference_p10_yoy_pct, 0)} to ${signedPct(u.reference_p90_yoy_pct, 0)}`}
          />
        </dl>
      ) : (
        <Note tone="warn">Unusualness was not assessed for this month: {u.text ?? u.reason}.</Note>
      )}
      {u.status === "ok" && u.stable === false && (
        <p className="mt-3 text-xs text-ink-3">Fewer than 60 earlier changes: the reference is short and the score less stable.</p>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div>
          <h3 className="text-sm font-semibold text-ink">Seasonal pattern before the episode</h3>
          {se.status === "ok" ? (
            <>
              <p className="mt-1 text-sm text-ink-2">
                The usual pattern from {se.years_used} earlier years implies {signedPct(se.expected_change_pct)} over these months
                {se.observed_change_pct != null && <>; the observed change was {signedPct(se.observed_change_pct)}</>}.{" "}
                {SEASON_TEXT[se.verdict ?? ""] ?? ""}
              </p>
              <p className="mt-1 text-xs text-ink-3">{se.method}</p>
            </>
          ) : (
            <p className="mt-1 text-sm text-ink-2">Not assessed: {se.reason ?? "too few earlier years"}.</p>
          )}
        </div>
        {sOption && (
          <div>
            <Chart ref={season} option={sOption} height={200} ariaLabel="Usual price by calendar month relative to the yearly average, before the episode" />
          </div>
        )}
      </div>
      <div className="mt-4">
        <h3 className="text-sm font-semibold text-ink">Persistence</h3>
        <p className="mt-1 text-sm text-ink-2">{persistenceText(d)}</p>
        {d.episode && (
          <p className="mt-1 text-xs text-ink-3" data-testid="episode-caveat">
            {d.persistence.note ?? "A detected episode is where the screening rule fired; it can split or truncate a longer disruption, so its length is not the duration of a real-world event."}
          </p>
        )}
      </div>
    </Panel>
  );
}

const SEASON_TEXT: Record<string, string> = {
  largely_seasonal: "Most of the movement matches the usual seasonal pattern.",
  partly_seasonal: "Part of the movement matches the usual seasonal pattern.",
  not_seasonal: "The movement goes well beyond, or against, the usual seasonal pattern.",
  no_base_observation: "The month before the episode was not observed, so the comparison cannot be made.",
};

function persistenceText(d: Investigation): string {
  const ps = d.persistence;
  const ep = d.episode;
  if (!ep) return "No episode of 12-month changes beyond the thresholds was found at this month.";
  const span = `${month(ep.start)} to ${month(ep.end)}`;
  const base =
    ps.verdict === "ongoing"
      ? `The screening rule flagged ${ep.duration_months} months since ${month(ep.start)} and the change was still elevated at the last observation.`
      : ps.verdict === "single_month"
        ? `The screening rule flagged a single month (${month(ep.start)}).`
        : `The screening rule flagged ${ep.duration_months} consecutive months, ${span}${ps.verdict === "persistent" ? " (persistent)" : ""}.`;
  const retrace =
    ep.retrace_6m_pct != null ? ` Six months after the peak the price was ${signedPct(ep.retrace_6m_pct)} relative to the peak.` : "";
  return base + retrace;
}

function zOption(p: Palette, d: Investigation) {
  const base = baseOption(p);
  const periods = d.signals.map((s) => s.period);
  const event = clampToPeriods(periods, d.config.event);
  return {
    ...base,
    grid: { left: 48, right: 20, top: 20, bottom: 36 },
    xAxis: { ...(base.xAxis as object), type: "category", data: periods },
    yAxis: { ...(base.yAxis as object), type: "value", name: "robust z" },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (ps: { dataIndex: number }[]) => {
        const s = d.signals[ps[0]?.dataIndex ?? 0];
        if (!s) return "";
        const z = s.z == null ? (s.status === "withheld" ? "not assessed" : "no 12-month change") : `z ${zText(s.z)}`;
        return `${month(s.period)}<br/>12-month change ${signedPct(s.yoy_pct)}<br/>${z}`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Robust z",
        barMaxWidth: 14,
        data: d.signals.map((s) => ({
          value: s.z,
          itemStyle: { color: s.z != null && Math.abs(s.z) >= 2 ? p.warn : p.neutral, opacity: s.period === event ? 1 : 0.75 },
        })),
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: p.ink3, type: "dashed" },
          label: { color: p.ink3, fontSize: 11, formatter: "{c}" },
          data: [{ yAxis: 2 }, { yAxis: -2 }],
        },
      },
    ],
  };
}

function bandSeries(p: Palette, lo: (number | null)[], hi: (number | null)[], name: string) {
  return [
    { type: "line", name: `${name} low`, stack: name, data: lo, symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
    {
      type: "line",
      name,
      stack: name,
      data: hi.map((h, i) => (h == null || lo[i] == null ? null : h - (lo[i] as number))),
      symbol: "none",
      lineStyle: { opacity: 0 },
      areaStyle: { color: p.rainSoft, opacity: 0.6 },
      itemStyle: { color: p.rainSoft },
      silent: true,
    },
  ];
}

function seasonOption(p: Palette, d: Investigation) {
  const base = baseOption(p);
  const m = d.seasonality.months ?? [];
  const pc = (v: number | null) => (v == null ? null : Math.round(v * 1000) / 10);
  return {
    ...base,
    grid: { left: 44, right: 12, top: 24, bottom: 28 },
    legend: { show: false },
    xAxis: { ...(base.xAxis as object), type: "category", data: m.map((x) => x.name) },
    yAxis: { ...(base.yAxis as object), type: "value", scale: true, name: "% of yearly mean" },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (ps: { dataIndex: number }[]) => {
        const x = m[ps[0]?.dataIndex ?? 0];
        if (!x) return "";
        const f = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
        return `${x.name}: median year ${f(x.median_index)}<br/>middle half of years ${f(x.q25)} to ${f(x.q75)} (${x.n_years} years)`;
      },
    },
    series: [
      ...bandSeries(p, m.map((x) => pc(x.q25)), m.map((x) => pc(x.q75)), "Middle half of years"),
      { type: "line", name: "Median year", data: m.map((x) => pc(x.median_index)), itemStyle: { color: p.rain }, lineStyle: { color: p.rain } },
    ],
  };
}

/* --- 4. comparable markets --------------------------------------------------------------------------- */

function Peers({ d }: { d: Investigation }) {
  const p = usePalette();
  const chart = useRef<ChartHandle>(null);
  const ex = d.peers.extent;
  const idx = d.peers.index;
  const option = useMemo(() => (p && idx.rows.length && idx.n_indexed_peers > 0 ? peerOption(p, d) : null), [p, d, idx]);
  return (
    <Panel
      id="peers"
      title="4. Comparable markets"
      note={`Same country, commodity, unit (${d.subject.unit}), price type (${d.subject.price_type}) and currency (${d.subject.currency}). No conversion between units or currencies is made.`}
      actions={option ? <PngButton chart={chart} name={`${d.config.series_id}-peers.png`} /> : undefined}
    >
      {ex.n_peers === 0 ? (
        <Empty>No other market reports this commodity in the same unit, price type and currency, so the movement cannot be compared.</Empty>
      ) : (
        <>
          <p className="text-ink">
            <strong>{EXTENT_LABEL[ex.class] ?? ex.class}.</strong> {extentSentence(ex, "comparable markets", d.peers.n_available)}
          </p>
          <p className="mt-1 text-xs text-ink-3">Rule: {ex.rule}</p>
          {option && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold text-ink">Price index, 12 months before the episode = 100</h3>
              <Chart ref={chart} option={option} height={260} ariaLabel="This market's price index against the median and middle half of comparable markets" />
              <p className="text-xs text-ink-3">
                {idx.n_indexed_peers} comparable markets with enough observations in the base period {idx.base ? `${month(idx.base.start)}–${month(idx.base.end)}` : ""}.
              </p>
            </div>
          )}
          <PeerTable rows={d.peers.rows} label="Comparable markets" capped={d.peers.capped_at} total={d.peers.n_available ?? ex.n_peers} first="market" />
        </>
      )}
    </Panel>
  );
}

/**
 * The comparator population as four nested counts (found, reported a change, assessable, unusual). The class
 * (widespread, local, ...) describes only the assessable ones, and the text says so.
 */
function extentSentence(ex: Investigation["peers"]["extent"], what: string, available?: number | null): string {
  const found = Math.max(available ?? ex.n_peers, ex.n_peers);
  const read = found > ex.n_peers ? ` (the ${ex.n_peers} best observed were read)` : "";
  const observed = ex.n_with_change != null ? `${ex.n_with_change} reported a 12-month change within a month of the peak; ` : "";
  const med = ex.median_peer_yoy_pct != null ? ` The median 12-month change was ${signedPct(ex.median_peer_yoy_pct)}.` : "";
  const head = `${found} ${what} found${read}; ${observed}`;
  if (ex.n_assessable === 0) return `${head}none had enough history to be assessed against its own past.${med}`;
  return `${head}${ex.n_assessable} had enough history to be assessed, and ${ex.n_elevated} of those ${ex.n_assessable} were also unusual in the same direction. The class describes only these ${ex.n_assessable} assessable ones.${med}`;
}

function peerOption(p: Palette, d: Investigation) {
  const base = baseOption(p);
  const rows = d.peers.index.rows;
  const r1 = (v: number | null) => (v == null ? null : Math.round(v * 10) / 10);
  return {
    ...base,
    grid: { left: 48, right: 20, top: 30, bottom: 36 },
    xAxis: { ...(base.xAxis as object), type: "category", data: rows.map((r) => r.period), boundaryGap: false },
    yAxis: { ...(base.yAxis as object), type: "value", scale: true },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (ps: { dataIndex: number }[]) => {
        const r = rows[ps[0]?.dataIndex ?? 0];
        if (!r) return "";
        const f = (v: number | null) => (v == null ? "—" : v.toFixed(1));
        return [
          month(r.period),
          `${d.subject.market_name}: ${r.own == null ? "no observation" : f(r.own)}`,
          `Comparable markets, median: ${f(r.peer_median)}`,
          `Middle half: ${f(r.peer_q25)} to ${f(r.peer_q75)} (${r.peers_observed} observed)`,
        ].join("<br/>");
      },
    },
    legend: { ...(base.legend as object), data: [d.subject.market_name, "Comparable markets (median)", "Middle half of comparable markets"] },
    series: [
      ...bandSeries(p, rows.map((r) => r1(r.peer_q25)), rows.map((r) => r1(r.peer_q75)), "Middle half of comparable markets"),
      { type: "line", name: "Comparable markets (median)", data: rows.map((r) => r1(r.peer_median)), symbol: "none", itemStyle: { color: p.rain }, lineStyle: { color: p.rain, width: 1.8 } },
      { type: "line", name: d.subject.market_name, data: rows.map((r) => r1(r.own)), connectNulls: false, symbolSize: 4, itemStyle: { color: p.ink }, lineStyle: { color: p.ink, width: 2 } },
    ],
  };
}

function PeerTable({ rows, label, capped, total, first }: { rows: PeerRow[]; label: string; capped: number; total: number; first: "market" | "commodity" }) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(
    () => [...rows].sort((a, b) => Number(b.elevated) - Number(a.elevated) || (b.z ?? -Infinity) - (a.z ?? -Infinity)),
    [rows],
  );
  const shown = all ? sorted : sorted.slice(0, 8);
  return (
    <div className="mt-4">
      <div className="relative -mx-5 overflow-x-auto px-5">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th scope="col" className="py-2 pr-3 font-medium">{first === "market" ? "Market" : "Food"}</th>
              <th scope="col" className="py-2 pr-3 font-medium">Month compared</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">12-month change</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Robust z</th>
              <th scope="col" className="py-2 font-medium">Also unusual?</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.series_id} className="border-b border-line/60">
                <td className="py-2 pr-3">
                  <Link href={`/market?series=${r.series_id}`} className="text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                    {first === "market" ? r.market_name : r.commodity_name}
                  </Link>
                  <span className="block text-xs text-ink-3">
                    {first === "market" ? r.admin1_name : `${r.price_type}, ${r.unit}`}
                  </span>
                </td>
                <td className="py-2 pr-3 text-ink-2">{month(r.period)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-ink">{signedPct(r.yoy_pct)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-ink">{r.status === "ok" ? zText(r.z) : <span className="text-xs text-ink-3">{r.reason ?? "not assessed"}</span>}</td>
                <td className="py-2 text-ink-2">{r.status !== "ok" ? "—" : r.elevated ? <Tag tone="warn">Yes</Tag> : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-3">
        {sorted.length > 8 && (
          <button type="button" className="text-rain underline print:hidden" onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show all ${sorted.length}`}
          </button>
        )}
        {total > capped && <span>Showing the {capped} with the most observations of {total}.</span>}
      </div>
    </div>
  );
}

/* --- 5. other foods in the market -------------------------------------------------------------------- */

function Breadth({ d }: { d: Investigation }) {
  const ex = d.breadth.extent;
  return (
    <Panel id="breadth" title="5. Other foods in the same market" note={`Every other food reported in ${d.subject.market_name} in ${d.subject.currency}, each against its own past.`}>
      {ex.n_peers === 0 ? (
        <Empty>No other food is reported in this market in the same currency.</Empty>
      ) : (
        <>
          <p className="text-ink">
            <strong>{EXTENT_LABEL[ex.class] ?? ex.class}.</strong> {extentSentence(ex, "other foods", d.breadth.n_available)}
          </p>
          <p className="mt-1 text-xs text-ink-3">Rule: {ex.rule}</p>
          <PeerTable rows={d.breadth.rows} label="Other foods in the same market" capped={d.breadth.capped_at} total={d.breadth.n_available ?? ex.n_peers} first="commodity" />
        </>
      )}
    </Panel>
  );
}

/* --- 6. context -------------------------------------------------------------------------------------- */

function Context({ d }: { d: Investigation }) {
  const w = d.context.weather;
  const m = d.context.macro;
  return (
    <Panel id="context" title="6. Context" note="Only data integrated in Market Almanac are shown. Missing context is reported as missing, never as zero.">
      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">Weather (contextual only)</h3>
          {w.status !== "ok" ? (
            <p className="mt-1 text-sm text-ink-2">Not available for this market: no weather grid cell or production region is integrated for it.</p>
          ) : (
            <ul className="mt-1 space-y-1 text-sm text-ink-2">
              {w.market_cell && (
                <li>
                  Market grid cell, {month(w.market_cell.window.start)}–{month(w.market_cell.window.end)}: mean rainfall anomaly{" "}
                  {w.market_cell.mean_rain_anomaly_z == null ? "not available" : `z ${z1(w.market_cell.mean_rain_anomaly_z)}`};{" "}
                  {w.market_cell.months_rain_below_minus_1_5} very dry and {w.market_cell.months_rain_above_1_5} very wet months (|z| ≥ 1.5).
                </li>
              )}
              {w.production_region && (
                <li>
                  Production region{w.production_region.crop ? ` (${w.production_region.crop})` : ""}: latest growing-season rainfall anomaly z{" "}
                  {z1(w.production_region.season_rain_anomaly_z)}, driest z {z1(w.production_region.min_season_rain_anomaly_z)} in the year before.
                </li>
              )}
              {w.note && <li className="text-xs text-ink-3">{w.note}</li>}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink">Inflation and exchange rate</h3>
          <ul className="mt-1 space-y-1 text-sm text-ink-2">
            <li>
              Consumer price index:{" "}
              {m.cpi ? (
                <>
                  {signedPct(m.cpi.yoy_pct)} over 12 months to {month(m.cpi.period)} ({m.cpi.provider}).
                  {m.real_yoy_pct != null && <> Deflated by it, the price change was {signedPct(m.real_yoy_pct)}.</>}
                </>
              ) : (
                "not integrated for this country and month."
              )}
            </li>
            <li>
              Exchange rate:{" "}
              {m.fx ? (
                <>
                  {signedPct(m.fx.yoy_pct)} over 12 months to {month(m.fx.period)} ({m.fx.indicator_name}, {m.fx.provider}).
                </>
              ) : (
                "not integrated for this country and month."
              )}
            </li>
          </ul>
        </div>
      </div>
    </Panel>
  );
}

/* --- 7. evidence ------------------------------------------------------------------------------------- */

const INFERENCE_TONE: Record<string, Tone> = { descriptive: "muted", associational: "neutral", predictive: "neutral", causal: "warn" };

function InferenceList({ items }: { items: InferenceItem[] }) {
  return (
    <ul className="mt-2 space-y-2">
      {items.map((x, i) => (
        <li key={i} className="flex flex-col gap-1 text-sm text-ink sm:flex-row sm:items-start sm:gap-3">
          <span className="shrink-0 sm:w-28">
            <Tag tone={INFERENCE_TONE[x.inference] ?? "muted"}>{x.inference}</Tag>
          </span>
          <span>{x.text}</span>
        </li>
      ))}
    </ul>
  );
}

const MECH_TONE: Record<string, Tone> = {
  consistent: "warn",
  partly_consistent: "neutral",
  less_likely: "muted",
  not_indicated: "muted",
  context_only: "muted",
  cannot_be_assessed: "muted",
};

function Evidence({ d }: { d: Investigation }) {
  const e = d.evidence;
  return (
    <Panel id="evidence" title="8. What the evidence supports" note="Generated by fixed rules from the numbers above; no language model is involved and nothing is inferred beyond the data shown.">
      <section aria-labelledby="ev-facts">
        <h3 id="ev-facts" className="text-sm font-semibold text-ink">Observed facts</h3>
        <InferenceList items={e.observed_facts} />
      </section>
      <section aria-labelledby="ev-quant" className="mt-5">
        <h3 id="ev-quant" className="text-sm font-semibold text-ink">Quantitative description</h3>
        <InferenceList items={e.quantitative} />
      </section>
      <section aria-labelledby="ev-mech" className="mt-6">
        <h3 id="ev-mech" className="text-sm font-semibold text-ink">Possible explanations, and what the data say about each</h3>
        <ul className="mt-2 divide-y divide-line rounded border border-line">
          {e.mechanisms.map((m) => (
            <li key={m.key} className="p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-ink">{m.name}</span>
                <Tag tone={MECH_TONE[m.status] ?? "muted"}>{m.status_text}</Tag>
              </div>
              <p className="mt-0.5 text-sm text-ink-2">{m.description}</p>
              {m.evidence_groups && m.evidence_groups.length > 0 ? (
                <div className="mt-2 space-y-2" data-testid={`evidence-groups-${m.key}`}>
                  {m.evidence_groups.map((g) => (
                    <div key={g.key}>
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{g.label}</h4>
                      <ul className="list-disc pl-5 text-sm text-ink-2">
                        {g.items.map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : (
                m.evidence.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-sm text-ink-2">
                    {m.evidence.map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                )
              )}
              {m.needed.length > 0 && <p className="mt-1 text-xs text-ink-3">Would need: {m.needed.join("; ")}.</p>}
            </li>
          ))}
        </ul>
      </section>
      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <section aria-labelledby="ev-gaps">
          <h3 id="ev-gaps" className="text-sm font-semibold text-ink">Evidence gaps</h3>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink-2">
            {e.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="ev-unsup">
          <h3 id="ev-unsup" className="text-sm font-semibold text-ink">What this investigation does not show</h3>
          <InferenceList items={e.unsupported} />
        </section>
      </div>
    </Panel>
  );
}

/* --- 8. method, reproducibility, export -------------------------------------------------------------- */

function Method({ d }: { d: Investigation }) {
  // Client-rendered (the route reads search params), so the origin is known when this renders.
  const [link] = useState(() => (typeof window === "undefined" ? undefined : window.location.origin));
  return (
    <Panel id="method" title="9. Method, reproducibility and export">
      <p className="text-sm text-ink-2">{d.method.text}</p>
      {d.evidence.rules?.screening && <p className="mt-2 text-sm text-ink-2" data-testid="screening-caveat">{d.evidence.rules.screening}</p>}
      <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
        <Def label="Configuration id" value={<code className="text-sm">{d.config_id}</code>} hint="same configuration and snapshot, same document" />
        <Def label="Price snapshot" value={<code className="text-sm">{d.config.snapshot_id}</code>} />
        <Def label="Method version" value={d.config.method_version} />
      </dl>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-2">Reproducible configuration</summary>
        <pre className="mt-2 overflow-x-auto rounded bg-surface-2 p-3 text-xs text-ink">{JSON.stringify(d.config, null, 2)}</pre>
      </details>

      <div className="mt-5 flex flex-wrap gap-2 print:hidden">
        <LinkButton href={exportUrl(d, "md", { link })} download>
          <FileText className="h-3.5 w-3.5" aria-hidden /> Research brief (Markdown)
        </LinkButton>
        <LinkButton href={exportUrl(d, "json")} download>
          <Download className="h-3.5 w-3.5" aria-hidden /> Full investigation (JSON)
        </LinkButton>
        {(["signals", "peers", "market", "index"] as const).map((t) => (
          <LinkButton key={t} href={exportUrl(d, "csv", { table: t })} download>
            <Download className="h-3.5 w-3.5" aria-hidden /> {TABLE_LABEL[t]} (CSV)
          </LinkButton>
        ))}
        <button type="button" onClick={() => window.print()} className="inline-flex h-8 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
          <Printer className="h-3.5 w-3.5" aria-hidden /> Print or save as PDF
        </button>
      </div>

      <h3 className="mt-6 text-sm font-semibold text-ink">Sources</h3>
      <ul className="mt-1 space-y-1 text-sm text-ink-2">
        {d.sources.map((s) => (
          <li key={s.name}>
            <a href={s.url} className="underline decoration-line underline-offset-2 hover:decoration-ink" rel="noreferrer" target="_blank">
              {s.name}
            </a>{" "}
            — {s.use}. {s.licence}.
          </li>
        ))}
      </ul>

      <h3 className="mt-6 text-sm font-semibold text-ink">Go further</h3>
      <ul className="mt-1 space-y-1 text-sm text-ink-2 print:hidden">
        <li>
          <Link className="text-ink underline decoration-line underline-offset-2" href={`/market?series=${d.config.series_id}`}>
            Market page for this series
          </Link>{" "}
          — the full history, seasonality, weather and provenance.
        </li>
        <li>
          <Link className="text-ink underline decoration-line underline-offset-2" href="/workbench">
            Research Workbench
          </Link>{" "}
          — test whether a pattern like this holds across many markets with a pre-specified, falsifiable design. A single investigation cannot.
        </li>
      </ul>
    </Panel>
  );
}

const TABLE_LABEL = { signals: "Monthly signals", peers: "Comparable markets", market: "Other foods", index: "Price index" };

/* --- small pieces ------------------------------------------------------------------------------------ */

function Def({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink">{value}</dd>
      {hint && <dd className="text-xs text-ink-3">{hint}</dd>}
    </div>
  );
}

function PngButton({ chart, name }: { chart: React.RefObject<ChartHandle | null>; name: string }) {
  return (
    <button
      type="button"
      onClick={() => chart.current?.downloadPng(name)}
      className="inline-flex h-8 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2 print:hidden"
    >
      <Download className="h-3.5 w-3.5" aria-hidden /> PNG
    </button>
  );
}
