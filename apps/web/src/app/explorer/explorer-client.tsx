"use client";

import { GitCompareArrows, Search } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";

import { MovementTag } from "@/components/market-bits";
import { Empty, ErrorState, Field, inputClass, Loading, Note, PageHeader, Panel, Select, Tag } from "@/components/ui";
import { loadingLabel, type Market } from "@/lib/api";
import { fmt, month, pct } from "@/lib/format";
import {
  incompatibility,
  TIER_LABEL,
  useGlobalCommodities,
  useGlobalCountries,
  useGlobalMarkets,
  useGlobalSeries,
  type GlobalSeries,
} from "@/lib/global-api";
import { useUrlState } from "@/lib/url-state";

const MarketMap = dynamic(() => import("@/components/market-map").then((m) => m.MarketMap), {
  ssr: false,
  loading: () => <div className="h-[380px] animate-pulse rounded-md bg-surface-2" aria-hidden />,
});

const PAGE = 50;

export function TierTag({ status }: { status: string }) {
  const t = TIER_LABEL[status] ?? { text: status, tone: "muted" as const };
  return <Tag tone={t.tone}>{t.text}</Tag>;
}

export function ExplorerClient() {
  const { get, set } = useUrlState();
  const countriesQ = useGlobalCountries();
  const countries = useMemo(() => countriesQ.data?.countries ?? [], [countriesQ.data]);
  const fallback = countries.find((c) => c.forecast_evaluated)?.country_iso3 ?? countries[0]?.country_iso3 ?? "";
  const country = get("country") || fallback;
  const commodity = get("commodity");
  const market = get("market");
  const unit = get("unit");
  const q = get("q");
  const sort = get("sort") || "name";
  const offset = Number(get("offset") || 0);
  const includeShort = get("short") === "1";
  const picked = (get("s") || "").split(",").filter(Boolean);
  const [meta, setMeta] = useState<Record<string, GlobalSeries>>({});

  const commodities = useGlobalCommodities(country || undefined, market || undefined);
  const markets = useGlobalMarkets(country || undefined, commodity || undefined);
  const series = useGlobalSeries(country || undefined, {
    commodity: commodity || undefined,
    market: market || undefined,
    unit: unit || undefined,
    q: q.length >= 2 ? q : undefined,
    usable_only: !includeShort,
    sort,
    limit: PAGE,
    offset,
  });
  const cov = countries.find((c) => c.country_iso3 === country);
  const chosen = (commodities.data?.items ?? []).find((c) => c.commodity_code === commodity);

  const mapMarkets: Market[] = useMemo(
    () =>
      (markets.data?.items ?? []).map((m) => ({
        id: m.market_code,
        provider: "hdx_hapi",
        country_iso3: m.country_iso3,
        market_code: m.market_code,
        name: m.market_name,
        admin1: m.admin1_name,
        admin2: m.admin2_name ?? null,
        // markets whose stored coordinates are missing or invalid are listed but never plotted
        lat: m.coordinate_status === "ok" ? m.lat : null,
        lon: m.coordinate_status === "ok" ? m.lon : null,
        weather_location_id: null,
        n_series: m.series,
        first_period: m.first_period,
        last_period: m.last_period,
        eligible_series: m.usable_series,
      })),
    [markets.data],
  );
  const plotted = mapMarkets.filter((m) => m.lat !== null).length;

  const toggle = (s: GlobalSeries) => {
    const id = s.series_id;
    const next = picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id].slice(-8);
    setMeta((m) => ({ ...m, [id]: s }));
    set({ s: next.join(",") || null });
  };
  const known = picked.map((id) => meta[id]).filter((s): s is GlobalSeries => !!s);
  const problem = incompatibility(known);
  const hardMix = problem !== null && !problem.startsWith("different currencies");

  const commodityOptions = (commodities.data?.items ?? [])
    .filter((c) => includeShort || c.usable_series > 0)
    .map((c) => ({ value: c.commodity_code, label: `${c.commodity_name} (${includeShort ? c.series : c.usable_series})` }));
  const marketOptions = (markets.data?.items ?? [])
    .filter((m) => includeShort || m.usable_series > 0)
    .map((m) => ({ value: m.market_code, label: m.admin1_name ? `${m.market_name} · ${m.admin1_name}` : m.market_name }));

  return (
    <div>
      <PageHeader
        title="Explore markets"
        lede="Monthly food prices reported by the World Food Programme, for every country with stored prices. Every price is shown with the month it describes, its currency and its reporting unit."
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[13rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)]">
        <Field label={`Country${countries.length ? ` (${countries.length})` : ""}`} htmlFor="f-country">
          <Select
            id="f-country"
            value={country}
            onChange={(v) => set({ country: v, commodity: null, market: null, unit: null, offset: null, s: null, q: null })}
            options={countries.map((c) => ({ value: c.country_iso3, label: c.name }))}
          />
        </Field>
        <Field label="Commodity" htmlFor="f-commodity">
          <Select
            id="f-commodity"
            value={commodity}
            onChange={(v) => set({ commodity: v || null, unit: null, offset: null })}
            placeholder="All commodities"
            options={commodityOptions}
          />
        </Field>
        <Field label="Market" htmlFor="f-market">
          <Select id="f-market" value={market} onChange={(v) => set({ market: v || null, offset: null })} placeholder="All markets" options={marketOptions} />
        </Field>
        <Field label="Search markets, regions and commodities" htmlFor="f-q">
          <form
            key={q}
            className="flex gap-2"
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              set({ q: String(new FormData(e.currentTarget).get("q") ?? "").trim() || null, offset: null });
            }}
          >
            <input id="f-q" name="q" defaultValue={q} placeholder="e.g. millet, Bamako" className={`${inputClass} w-full`} />
            <button type="submit" className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink hover:bg-surface-2" aria-label="Search">
              <Search className="h-4 w-4" aria-hidden />
            </button>
          </form>
        </Field>
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-2">
        {chosen && chosen.units.length > 1 && (
          <Field label="Reporting unit" htmlFor="f-unit">
            <Select id="f-unit" value={unit} onChange={(v) => set({ unit: v || null, offset: null })} placeholder="All units" options={chosen.units.map((u) => ({ value: u, label: u }))} />
          </Field>
        )}
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={includeShort}
            onChange={(e) => set({ short: e.target.checked ? "1" : null, offset: null })}
            className="h-4 w-4 accent-[var(--rain)]"
          />
          Include short histories (fewer than 12 monthly prices)
        </label>
        {chosen && chosen.units.length > 1 && (
          <span className="text-xs text-ink-3">This commodity is reported in {chosen.units.length} units here; each unit is a separate series and they are never combined.</span>
        )}
      </div>

      {countriesQ.isError && <ErrorState error={countriesQ.error} what="the country inventory" />}
      {countriesQ.isLoading && <Loading label={loadingLabel(countriesQ, "Loading countries")} />}
      {cov && (
        <div className="mb-5 space-y-2 text-sm text-ink-2" data-testid="country-summary">
          <p>
            <strong className="font-medium text-ink">{cov.name}</strong> <TierTag status={cov.status} /> · {cov.markets.toLocaleString()} markets, {cov.commodities} commodities,{" "}
            {cov.series.toLocaleString()} series ({cov.usable_series.toLocaleString()} with at least a year of prices), {cov.observations.toLocaleString()} stored records,{" "}
            {month(cov.first_period)} to {month(cov.last_period)}. Currency: {cov.currencies.join(", ") || "not stated"}.
          </p>
          <p className="text-ink-3">
            {cov.status_note}.{" "}
            {cov.forecast_evaluated
              ? `${cov.evaluations} published evaluation${cov.evaluations === 1 ? "" : "s"} cover this country.`
              : "No forecast is shown for this country because no forecast evaluation covers it; price history only."}{" "}
            <Link href={`/atlas?country=${cov.country_iso3}`} className="underline">
              Coverage record
            </Link>
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Panel
          title="Markets"
          note={
            markets.data
              ? `${markets.data.total.toLocaleString()} markets · ${plotted.toLocaleString()} plotted${
                  markets.data.markets_without_valid_coordinates ? ` · ${markets.data.markets_without_valid_coordinates} have missing or invalid coordinates and are listed but not plotted` : ""
                }`
              : undefined
          }
        >
          {markets.isLoading ? (
            <Loading label={loadingLabel(markets, "Loading markets")} />
          ) : markets.isError ? (
            <ErrorState error={markets.error} what="markets" />
          ) : plotted === 0 ? (
            <Empty>No market in this country has usable coordinates, so there is no map. Use the market filter or the table to browse its series.</Empty>
          ) : (
            <MarketMap markets={mapMarkets} selected={market || undefined} onSelect={(id) => set({ market: id, offset: null })} />
          )}
          <p className="mt-2 text-xs text-ink-3">Select a marker to list that market&rsquo;s series. Filled markers have at least one series with a year of data.</p>
        </Panel>

        <Panel
          title="Price series"
          note={
            series.data
              ? `${series.data.total.toLocaleString()} series match · one series = one market, commodity, unit, price type and currency`
              : undefined
          }
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
                    { value: "coverage", label: "Most complete" },
                    { value: "movement", label: "Most unusual move" },
                  ]}
                />
              </Field>
            </div>
          }
        >
          {series.isLoading && <Loading label={loadingLabel(series, "Loading series")} />}
          {series.isError && <ErrorState error={series.error} what="price series" />}
          {series.data && series.data.items.length === 0 && (
            <Empty>
              No series match these filters.{" "}
              {!includeShort
                ? "Series with fewer than 12 monthly prices are hidden; tick “Include short histories” to list them. "
                : ""}
              Clear the search or choose another commodity or market.
            </Empty>
          )}
          {series.data && series.data.items.length > 0 && (
            <>
              <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Price series table">
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-xs text-ink-3">
                      <th className="w-8 py-2 pr-2 font-medium">
                        <span className="sr-only">Compare</span>
                      </th>
                      <th className="py-2 pr-3 font-medium">Commodity · market</th>
                      <th className="py-2 pr-3 text-right font-medium">Latest price</th>
                      <th className="py-2 pr-3 text-right font-medium">History</th>
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
                            onChange={() => toggle(s)}
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
                            {s.price_type} · {s.unit}
                            {s.coordinate_status !== "ok" ? ` · coordinates ${s.coordinate_status}` : ""}
                          </div>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right">
                          <div className="text-ink">
                            {fmt(s.latest_price)} <span className="text-xs text-ink-3">{s.currency}/{s.unit}</span>
                          </div>
                          <div className={`text-xs ${s.months_behind_dataset > 3 ? "text-warn" : "text-ink-3"}`}>observed {month(s.last_period)}</div>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-ink-2">
                          <div>
                            {s.n_observations} of {s.months_spanned} months
                          </div>
                          <div className={`text-xs ${s.missing_months > 0 ? "text-ink-3" : "text-ink-3"}`}>
                            {s.missing_months > 0 ? `${s.missing_months} missing · longest gap ${s.longest_gap_months}` : "no gaps"}
                            {s.n_conflicting_duplicates > 0 ? ` · ${s.n_conflicting_duplicates} conflicting` : ""}
                          </div>
                          {!s.usable && <div className="text-xs text-warn">short history</div>}
                        </td>
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
                  <button type="button" disabled={offset === 0} onClick={() => set({ offset: offset - PAGE > 0 ? String(offset - PAGE) : null })} className="rounded border border-line px-3 py-1 text-ink disabled:opacity-40">
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
            {picked.length} series selected for comparison
            {problem ? `. They have ${problem}${hardMix ? ", so they cannot be compared." : "."}` : "."}
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={() => set({ s: null })} className="rounded border border-line px-3 py-1.5 text-sm text-ink">
              Clear
            </button>
            <Link
              href={`/compare?s=${picked.join(",")}`}
              aria-disabled={picked.length < 2 || hardMix}
              className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium ${picked.length < 2 || hardMix ? "pointer-events-none bg-surface-2 text-ink-3" : "bg-ink text-bg"}`}
            >
              <GitCompareArrows className="h-4 w-4" aria-hidden /> Compare
            </Link>
          </div>
        </div>
      )}

      <div className="mt-6 space-y-3">
        <Note>
          &ldquo;Latest move&rdquo; compares the most recent monthly change with the same series&rsquo; earlier changes. It is a statistical description of one
          series, not a finding of a shortage or a crisis. The method is on each market page.
        </Note>
        <Note>
          Prices are shown in the currency and unit in which they were reported. Series in different currencies or units are never added together or
          converted; the comparison page indexes series to their own starting month and refuses incompatible commodities, units and price types.
        </Note>
      </div>
    </div>
  );
}
