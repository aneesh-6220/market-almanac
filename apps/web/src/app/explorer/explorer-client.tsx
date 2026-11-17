"use client";

import { GitCompareArrows, Search } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";

import { MovementTag } from "@/components/market-bits";
import { Empty, ErrorState, Field, inputClass, Loading, Note, PageHeader, Panel, Select } from "@/components/ui";
import type { Market } from "@/lib/api";
import { fmt, month, pct } from "@/lib/format";
import { useCatalog, useCatalogCommodities, useCatalogMarkets, useCoverageSummary } from "@/lib/market-api";
import { useUrlState } from "@/lib/url-state";

const MarketMap = dynamic(() => import("@/components/market-map").then((m) => m.MarketMap), {
  ssr: false,
  loading: () => <div className="h-[380px] animate-pulse rounded-md bg-surface-2" aria-hidden />,
});

const PAGE = 50;

export function ExplorerClient() {
  const { get, set } = useUrlState();
  const coverage = useCoverageSummary();
  const countries = coverage.data?.countries ?? [];
  const country = get("country") || countries[0]?.country_iso3 || "";
  const commodity = get("commodity");
  const market = get("market");
  const q = get("q");
  const sort = get("sort") || "name";
  const offset = Number(get("offset") || 0);
  const [draft, setDraft] = useState(q);
  const picked = (get("s") || "").split(",").filter(Boolean);

  const commodities = useCatalogCommodities(country || undefined);
  const markets = useCatalogMarkets(country || undefined, commodity || undefined);
  const series = useCatalog(
    { country: country || undefined, commodity: commodity || undefined, market: market || undefined, q: q.length >= 2 ? q : undefined, sort, limit: PAGE, offset },
    !!country,
  );
  const cov = countries.find((c) => c.country_iso3 === country);

  const mapMarkets: Market[] = useMemo(
    () =>
      (markets.data ?? []).map((m) => ({
        id: m.market_code,
        provider: "hdx_hapi",
        country_iso3: m.country_iso3,
        market_code: m.market_code,
        name: m.market_name,
        admin1: m.admin1_name,
        admin2: null,
        lat: m.lat,
        lon: m.lon,
        weather_location_id: null,
        n_series: m.series,
        first_period: null,
        last_period: m.last_period,
        eligible_series: m.usable_series,
      })),
    [markets.data],
  );

  const toggle = (id: string) => {
    const next = picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id].slice(-8);
    set({ s: next.join(",") || null });
  };
  const pickedRows = (series.data?.items ?? []).filter((s) => picked.includes(s.series_id));
  const mixed = new Set(pickedRows.map((s) => `${s.commodity_name}|${s.unit}|${s.price_type}`)).size > 1;

  return (
    <div>
      <PageHeader
        title="Explore markets"
        lede="Monthly food prices reported by the World Food Programme, by country, commodity and market. Every price is shown with the month it was observed."
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[12rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)]">
        <Field label="Country" htmlFor="f-country">
          <Select
            id="f-country"
            value={country}
            onChange={(v) => set({ country: v, commodity: null, market: null, offset: null, s: null })}
            options={countries.map((c) => ({ value: c.country_iso3, label: c.name }))}
          />
        </Field>
        <Field label="Commodity" htmlFor="f-commodity">
          <Select
            id="f-commodity"
            value={commodity}
            onChange={(v) => set({ commodity: v || null, offset: null })}
            placeholder="All commodities"
            options={(commodities.data ?? []).filter((c) => c.usable_series > 0).map((c) => ({ value: c.commodity_code, label: `${c.commodity_name} (${c.usable_series})` }))}
          />
        </Field>
        <Field label="Market" htmlFor="f-market">
          <Select
            id="f-market"
            value={market}
            onChange={(v) => set({ market: v || null, offset: null })}
            placeholder="All markets"
            options={(markets.data ?? []).filter((m) => m.usable_series > 0).map((m) => ({ value: m.market_code, label: m.admin1_name ? `${m.market_name} · ${m.admin1_name}` : m.market_name }))}
          />
        </Field>
        <Field label="Search markets and commodities" htmlFor="f-q">
          <form
            className="flex gap-2"
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              set({ q: draft.trim() || null, offset: null });
            }}
          >
            <input id="f-q" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="e.g. millet, Bamako" className={`${inputClass} w-full`} />
            <button type="submit" className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink hover:bg-surface-2" aria-label="Search">
              <Search className="h-4 w-4" aria-hidden />
            </button>
          </form>
        </Field>
      </div>

      {coverage.isError && <ErrorState error={coverage.error} what="the coverage inventory" />}
      {cov && (
        <p className="mb-5 text-sm text-ink-2">
          <strong className="font-medium text-ink">{cov.name}</strong>: {cov.markets} markets, {cov.commodities} commodities,{" "}
          {cov.usable_series.toLocaleString()} series with at least a year of prices, {month(cov.first_period)} to {month(cov.last_period)}.{" "}
          {cov.forecast_evaluated_series > 0
            ? `${cov.forecast_evaluated_series} series are covered by a forecast evaluation.`
            : "No forecast evaluation covers this country; it is available for price history only."}{" "}
          <Link href="/data" className="underline">
            Coverage details
          </Link>
        </p>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Panel title="Markets" note={markets.data ? `${markets.data.filter((m) => m.lat !== null).length} of ${markets.data.length} markets have coordinates` : undefined}>
          {markets.isLoading ? <Loading label="Loading markets" /> : <MarketMap markets={mapMarkets} selected={market || undefined} onSelect={(id) => set({ market: id, offset: null })} />}
          <p className="mt-2 text-xs text-ink-3">Select a marker to list that market&rsquo;s series. Filled markers have at least one series with a year of data.</p>
        </Panel>

        <Panel
          title="Price series"
          note={series.data ? `${series.data.total.toLocaleString()} series match · one series = one market, commodity, unit, price type and currency` : undefined}
          actions={
            <div className="flex items-end gap-2">
              <Field label="Sort" htmlFor="f-sort">
                <Select
                  id="f-sort"
                  value={sort}
                  onChange={(v) => set({ sort: v === "name" ? null : v, offset: null })}
                  options={[
                    { value: "name", label: "Name" },
                    { value: "latest", label: "Most recent" },
                    { value: "observations", label: "Longest history" },
                    { value: "movement", label: "Most unusual move" },
                  ]}
                />
              </Field>
            </div>
          }
        >
          {series.isLoading && <Loading label="Loading series" />}
          {series.isError && <ErrorState error={series.error} what="price series" />}
          {series.data && series.data.items.length === 0 && (
            <Empty>No series match these filters. Clear the search or choose another commodity or market.</Empty>
          )}
          {series.data && series.data.items.length > 0 && (
            <>
              <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Price series table">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-xs text-ink-3">
                      <th className="w-8 py-2 pr-2 font-medium">
                        <span className="sr-only">Compare</span>
                      </th>
                      <th className="py-2 pr-3 font-medium">Commodity · market</th>
                      <th className="py-2 pr-3 text-right font-medium">Latest price</th>
                      <th className="py-2 pr-3 text-right font-medium">1 month</th>
                      <th className="py-2 pr-3 text-right font-medium">12 months</th>
                      <th className="py-2 font-medium">Latest move</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series.data.items.map((s) => (
                      <tr key={s.series_id} className="border-b border-line/60 align-top">
                        <td className="py-2 pr-2">
                          <input
                            type="checkbox"
                            checked={picked.includes(s.series_id)}
                            onChange={() => toggle(s.series_id)}
                            aria-label={`Add ${s.commodity_name} in ${s.market_name} to comparison`}
                            className="h-4 w-4 accent-[var(--rain)]"
                          />
                        </td>
                        <td className="max-w-[18rem] py-2 pr-3">
                          <Link href={`/market?series=${s.series_id}`} className="font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                            {s.commodity_name}
                          </Link>
                          <div className="truncate text-ink-2" title={s.market_name}>
                            {s.market_name}
                            {s.admin1_name ? ` · ${s.admin1_name}` : ""}
                          </div>
                          <div className="text-xs text-ink-3">
                            {s.price_type} · {s.n_observations} months since {month(s.first_period)}
                          </div>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right">
                          <div className="text-ink">
                            {fmt(s.latest_price)} <span className="text-xs text-ink-3">{s.currency}/{s.unit}</span>
                          </div>
                          <div className={`text-xs ${s.months_behind_dataset > 3 ? "text-warn" : "text-ink-3"}`}>observed {month(s.last_period)}</div>
                        </td>
                        <td className="py-2 pr-3 text-right text-ink-2">{s.change_1m == null ? "—" : `${s.change_1m > 0 ? "+" : ""}${pct(s.change_1m, 1)}`}</td>
                        <td className="py-2 pr-3 text-right text-ink-2">{s.change_12m == null ? "—" : `${s.change_12m > 0 ? "+" : ""}${pct(s.change_12m, 1)}`}</td>
                        <td className="py-2">
                          <MovementTag label={s.movement_label} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-3">
                <span>
                  {offset + 1}–{Math.min(offset + PAGE, series.data.total)} of {series.data.total.toLocaleString()}
                </span>
                <div className="flex gap-2">
                  <button type="button" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) || null })} className="rounded border border-line px-3 py-1 text-ink disabled:opacity-40">
                    Previous
                  </button>
                  <button type="button" disabled={offset + PAGE >= series.data.total} onClick={() => set({ offset: String(offset + PAGE) })} className="rounded border border-line px-3 py-1 text-ink disabled:opacity-40">
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </Panel>
      </div>

      {picked.length > 0 && (
        <div className="sticky bottom-3 z-10 mt-5 flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface p-3 shadow-sm" role="status">
          <span className="text-sm text-ink-2">
            {picked.length} series selected for comparison{mixed ? ". They differ in commodity, unit or price type, so they cannot be compared." : "."}
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={() => set({ s: null })} className="rounded border border-line px-3 py-1.5 text-sm text-ink">
              Clear
            </button>
            <Link
              href={`/compare?s=${picked.join(",")}`}
              aria-disabled={picked.length < 2}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium ${picked.length < 2 ? "pointer-events-none bg-surface-2 text-ink-3" : "bg-ink text-bg"}`}
            >
              <GitCompareArrows className="h-4 w-4" aria-hidden /> Compare
            </Link>
          </div>
        </div>
      )}

      <div className="mt-6">
        <Note>
          &ldquo;Latest move&rdquo; compares the most recent monthly change with the same series&rsquo; earlier changes. It is a statistical description of one
          series, not a finding of a shortage or a crisis. The method is on each market page.
        </Note>
      </div>
    </div>
  );
}
