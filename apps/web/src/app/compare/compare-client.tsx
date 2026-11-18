"use client";

import { Download, Plus, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { baseOption, Chart, type ChartHandle, usePalette } from "@/components/chart";
import { CopyButton, signedPct } from "@/components/market-bits";
import { Empty, ErrorState, Field, inputClass, Loading, Note, PageHeader, Panel, Select, Tag } from "@/components/ui";
import { fmt, month, pct } from "@/lib/format";
import { useGlobalCountries, useGlobalSeries } from "@/lib/global-api";
import { compareUrl, useCompare, useSeriesDetail, type CatalogSeries, type Compare } from "@/lib/market-api";
import { useUrlState } from "@/lib/url-state";

const MAX = 8;
const HUES = ["grain", "rain", "heat", "good", "bad", "neutral", "warn", "ink2"] as const;

function label(s: CatalogSeries) {
  return `${s.market_name} (${s.country_iso3})`;
}

function CompareChart({ data, mode, chartRef }: { data: Compare; mode: "index" | "price"; chartRef: React.Ref<ChartHandle> }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const b = baseOption(p);
    const first = data.series_meta[0];
    return {
      ...b,
      grid: { ...(b.grid as object), top: 44, bottom: 62 },
      legend: { ...(b.legend as object), type: "scroll", left: 0, right: 0 },
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number | null) => (v == null ? "no observation" : mode === "index" ? v.toFixed(1) : `${fmt(v)} ${first.currency}/${first.unit}`) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: {
        ...(b.yAxis as object),
        type: "value",
        scale: true,
        name: mode === "index" ? `index, ${data.index_base?.base_period ? `${month(data.index_base.base_period)} = 100` : "first observation = 100"}` : `${first.currency} per ${first.unit}`,
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, borderColor: p.line, textStyle: { color: p.ink3 } }],
      series: data.series_meta.map((s, i) => {
        const color = p[HUES[i % HUES.length]];
        return {
          name: label(s),
          type: "line",
          showSymbol: false,
          connectNulls: false,
          lineStyle: { color, width: 2 },
          itemStyle: { color },
          data: data.rows.map((r) => [r.period, mode === "index" ? r.index[s.series_id] : r.prices[s.series_id]]),
        };
      }),
    };
  }, [p, data, mode]);
  return <Chart ref={chartRef} option={option} height={380} ariaLabel={mode === "index" ? "Indexed price movements by market" : "Price levels by market"} />;
}

function AddSeries({ anchor, taken, onAdd }: { anchor: CatalogSeries; taken: string[]; onAdd: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [iso, setIso] = useState(anchor.country_iso3);
  const countries = useGlobalCountries();
  const same = iso === anchor.country_iso3;
  // the same commodity code identifies the commodity within a country; across countries match on its name
  const found = useGlobalSeries(iso, {
    commodity: same ? anchor.commodity_code : undefined,
    unit: anchor.unit,
    price_type: anchor.price_type,
    q: same ? (q.trim().length >= 2 ? q.trim() : undefined) : anchor.commodity_name.length >= 2 ? anchor.commodity_name : undefined,
    sort: "observations",
    limit: same ? 60 : 100,
  });
  const needle = q.trim().toLowerCase();
  const options = (found.data?.items ?? []).filter(
    (s) =>
      !taken.includes(s.series_id) &&
      s.unit === anchor.unit &&
      s.price_type === anchor.price_type &&
      (same || s.commodity_name === anchor.commodity_name) &&
      (same || !needle || `${s.market_name} ${s.admin1_name ?? ""}`.toLowerCase().includes(needle)),
  );
  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_14rem]">
        <Field label={`Find another market selling ${anchor.commodity_name} (${anchor.price_type.toLowerCase()}, per ${anchor.unit})`} htmlFor="c-q">
          <input id="c-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Market or region name" className={inputClass} />
        </Field>
        <Field label="Country" htmlFor="c-scope">
          <Select
            id="c-scope"
            value={iso}
            onChange={setIso}
            options={(countries.data?.countries ?? [{ country_iso3: anchor.country_iso3, name: anchor.country_iso3 }]).map((c) => ({ value: c.country_iso3, label: c.name }))}
          />
        </Field>
      </div>
      {!same && (
        <p className="mt-2 text-xs text-ink-3">
          Series from another country are priced in another currency. They are compared only as indices; prices are never converted.
        </p>
      )}
      {found.isLoading && <Loading label="Searching" />}
      {found.data && options.length === 0 && (
        <p className="mt-3 text-sm text-ink-3">No further comparable series found. Only series with the same commodity, unit and price type are offered.</p>
      )}
      <ul className="mt-3 grid max-h-64 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2" aria-label="Comparable series">
        {options.map((s) => (
          <li key={s.series_id}>
            <button
              type="button"
              disabled={taken.length >= MAX}
              onClick={() => onAdd(s.series_id)}
              className="flex w-full items-center justify-between gap-2 rounded border border-line px-2.5 py-1.5 text-left text-sm hover:bg-surface-2 disabled:opacity-40"
            >
              <span className="min-w-0">
                <span className="block truncate text-ink">{label(s)}</span>
                <span className="block truncate text-xs text-ink-3">
                  {s.n_observations} months · to {month(s.last_period)} · {s.currency}
                </span>
              </span>
              <Plus className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CompareClient() {
  const { get, set } = useUrlState();
  const ids = useMemo(() => Array.from(new Set((get("s") || "").split(",").filter((x) => /^ps_[0-9a-f]{16}$/.test(x)))).slice(0, MAX), [get]);
  const view = get("view") === "price" ? "price" : "index";
  const anchor = useSeriesDetail(ids[0]);
  const cmp = useCompare(ids);
  const chartRef = useRef<ChartHandle>(null);
  const setIds = (next: string[]) => set({ s: next.join(",") || null });

  const data = cmp.data;
  const meta = data?.series_meta ?? [];
  const canPrice = !!data?.comparability.absolute;
  const mode = view === "price" && canPrice ? "price" : "index";
  const byId = Object.fromEntries(meta.map((m) => [m.series_id, m]));

  return (
    <div>
      <PageHeader
        title="Compare markets"
        lede="Put the same commodity in different markets side by side. Levels are compared only where unit and currency match; otherwise movements are compared as indices."
      >
        {ids.length >= 2 && <CopyButton label="Copy link" icon="share" text={() => window.location.href} />}
      </PageHeader>

      {ids.length === 0 && (
        <Empty>
          No series selected. In the <Link className="underline" href="/explorer">explorer</Link>, tick two or more series of the same commodity and choose Compare, or open a market and
          use &ldquo;Compare with other markets&rdquo;.
        </Empty>
      )}

      {ids.length > 0 && (
        <Panel title="Selected series" note={`${ids.length} of ${MAX}`}>
          <ul className="flex flex-wrap gap-2">
            {ids.map((id, i) => {
              const m = byId[id] ?? (i === 0 ? anchor.data?.series : undefined);
              return (
                <li key={id} className="inline-flex max-w-full items-center gap-2 rounded border border-line bg-surface-2 py-1 pl-2.5 pr-1 text-sm">
                  <Link href={`/market?series=${id}`} className="truncate text-ink underline decoration-line underline-offset-2">
                    {m ? `${m.commodity_name} · ${label(m)}` : id}
                  </Link>
                  <button type="button" onClick={() => setIds(ids.filter((x) => x !== id))} aria-label={`Remove ${m ? label(m) : id}`} className="rounded p-1 text-ink-3 hover:bg-surface hover:text-ink">
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
          {anchor.data && ids.length < MAX && (
            <details className="mt-4 border-t border-line pt-3" open={ids.length < 2}>
              <summary className="cursor-pointer text-sm font-medium text-rain">Add a market</summary>
              <div className="mt-3">
                <AddSeries anchor={anchor.data.series} taken={ids} onAdd={(id) => setIds([...ids, id])} />
              </div>
            </details>
          )}
          {anchor.isError && <ErrorState error={anchor.error} what="the first series" />}
        </Panel>
      )}

      {ids.length === 1 && (
        <div className="mt-5">
          <Empty>Add at least one more market to compare.</Empty>
        </div>
      )}

      {ids.length >= 2 && (
        <div className="mt-5 space-y-5">
          {cmp.isLoading && <Loading label="Comparing" />}
          {cmp.isError && <ErrorState error={cmp.error} what="the comparison" />}

          {data && data.status === "not_comparable" && (
            <div role="alert" className="rounded-md border border-warn/40 bg-warn/10 p-4 text-sm text-ink" data-testid="not-comparable">
              <p className="font-medium">These series cannot be compared.</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-2">
                {data.comparability.reasons.map((r) => (
                  <li key={r}>{r.charAt(0).toUpperCase() + r.slice(1)}.</li>
                ))}
              </ul>
            </div>
          )}
          {data && data.status === "no_overlapping_data" && <Empty>The selected series have no observations in the chosen window.</Empty>}

          {data && data.status === "ok" && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Tag tone={canPrice ? "good" : "warn"}>{canPrice ? "Levels and movements comparable" : "Movements only (indexed)"}</Tag>
                <span className="text-ink-3">
                  {data.window?.months} months, {month(data.window?.start)} to {month(data.window?.end)} · all series observed in {data.months_all_observed} of them
                </span>
              </div>
              {data.comparability.reasons.map((r) => (
                <Note key={r} tone="warn">
                  {r.charAt(0).toUpperCase() + r.slice(1)}.
                </Note>
              ))}
              {data.index_base?.warning && <Note tone="warn">{data.index_base.warning}.</Note>}

              <Panel
                title={mode === "index" ? "Indexed movements" : "Price levels"}
                note={mode === "index" ? "Each series is divided by its own value in the base month. An index compares movements, not price levels or living costs." : "Nominal prices in the unit and currency reported."}
                actions={
                  <div className="flex flex-wrap items-end gap-2">
                    <Field label="Show" htmlFor="c-view">
                      <Select
                        id="c-view"
                        value={mode}
                        onChange={(v) => set({ view: v === "index" ? null : v })}
                        options={[{ value: "index", label: "Indexed (base = 100)" }, ...(canPrice ? [{ value: "price", label: "Price levels" }] : [])]}
                      />
                    </Field>
                    <button type="button" onClick={() => chartRef.current?.downloadPng("market_almanac_comparison.png")} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
                      <Download className="h-3.5 w-3.5" aria-hidden /> PNG
                    </button>
                    <a href={compareUrl(ids, undefined, undefined, "csv")} className="inline-flex h-9 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
                      <Download className="h-3.5 w-3.5" aria-hidden /> CSV
                    </a>
                  </div>
                }
              >
                <CompareChart data={data} mode={mode} chartRef={chartRef} />
              </Panel>

              <Panel title="Series in this comparison" note="Change over window uses each series' own first and last observation in the window.">
                <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Comparison statistics">
                  <table className="w-full min-w-[720px] text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-xs text-ink-3">
                        <th className="py-2 pr-3 font-medium">Market</th>
                        <th className="py-2 pr-3 font-medium">Unit</th>
                        <th className="py-2 pr-3 text-right font-medium">Latest price</th>
                        <th className="py-2 pr-3 font-medium">Observed for</th>
                        <th className="py-2 pr-3 text-right font-medium">Change over window</th>
                        <th className="py-2 pr-3 text-right font-medium">Index now</th>
                        <th className="py-2 text-right font-medium">Missing months</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.series.map((r) => {
                        const m = byId[r.series_id];
                        return (
                          <tr key={r.series_id} className="border-b border-line/60">
                            <td className="max-w-[16rem] truncate py-2 pr-3 text-ink" title={m?.market_name}>
                              <Link className="underline decoration-line underline-offset-2" href={`/market?series=${r.series_id}`}>
                                {m ? label(m) : r.series_id}
                              </Link>
                            </td>
                            <td className="py-2 pr-3 text-ink-2">
                              {m?.currency}/{m?.unit}
                            </td>
                            <td className="py-2 pr-3 text-right text-ink">{fmt(r.last_price)}</td>
                            <td className="py-2 pr-3 text-ink-2">{month(r.last_period)}</td>
                            <td className="py-2 pr-3 text-right text-ink-2">
                              {signedPct(r.pct_change_over_window)} <span className="text-xs text-ink-3">/ {r.window_months} mo</span>
                            </td>
                            <td className="py-2 pr-3 text-right text-ink-2">{r.last_index == null ? "—" : r.last_index.toFixed(1)}</td>
                            <td className={`py-2 text-right ${r.missing_share > 0.2 ? "text-warn" : "text-ink-2"}`}>{pct(r.missing_share)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {data.latest_common_spread && (
                  <p className="mt-3 text-sm text-ink-2">
                    In {month(data.latest_common_spread.period)}, the latest month with a price for every series, the highest price ({fmt(data.latest_common_spread.max)},{" "}
                    {byId[data.latest_common_spread.highest_series] ? label(byId[data.latest_common_spread.highest_series]) : ""}) was{" "}
                    {((data.latest_common_spread.max_over_min - 1) * 100).toFixed(0)}% above the lowest ({fmt(data.latest_common_spread.min)},{" "}
                    {byId[data.latest_common_spread.lowest_series] ? label(byId[data.latest_common_spread.lowest_series]) : ""}).
                  </p>
                )}
                {data.pairs.some((x) => x.correlation_of_monthly_changes != null) && (
                  <p className="mt-2 text-sm text-ink-2">
                    Correlation of monthly changes:{" "}
                    {data.pairs
                      .filter((x) => x.correlation_of_monthly_changes != null)
                      .slice(0, 6)
                      .map((x) => `${byId[x.a]?.market_name ?? x.a} – ${byId[x.b]?.market_name ?? x.b} ${x.correlation_of_monthly_changes!.toFixed(2)} (n=${x.n})`)
                      .join("; ")}
                    .
                  </p>
                )}
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-3">
                  {data.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </Panel>
            </>
          )}
        </div>
      )}
    </div>
  );
}
