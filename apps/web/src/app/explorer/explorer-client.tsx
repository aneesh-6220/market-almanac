"use client";

import Link from "next/link";
import { useEffect, useMemo } from "react";

import { MarketMap } from "@/components/market-map";
import { PriceChart, WeatherChart } from "@/components/series-charts";
import { Empty, ErrorState, Field, inputClass, Loading, Note, PageHeader, Panel, Select, Tag } from "@/components/ui";
import { month, pct } from "@/lib/format";
import { useCommodities, useCountries, useMarkets, usePrices, useSeries, useWeather } from "@/lib/queries";
import { useUrlState } from "@/lib/url-state";

export function ExplorerClient() {
  const { get, set } = useUrlState();
  const country = get("country");
  const commodity = get("commodity");
  const marketId = get("market");
  const seriesId = get("series");
  const from = get("from");
  const to = get("to");

  const countries = useCountries();
  const commodities = useCommodities(country || undefined);
  const markets = useMarkets(country || undefined, commodity || undefined);

  useEffect(() => {
    if (!country && countries.data?.length) set({ country: countries.data[0].iso3 });
  }, [country, countries.data, set]);

  const market = markets.data?.find((m) => m.id === marketId);
  const series = useSeries({ country: country || undefined, market: market?.market_code, commodity: commodity || undefined });
  const marketSeries = market ? series.data ?? [] : [];
  const selectedSeries = marketSeries.find((s) => s.series_id === seriesId) ?? marketSeries.find((s) => s.eligible) ?? marketSeries[0];
  const prices = usePrices(selectedSeries?.series_id);
  const weather = useWeather(market?.weather_location_id);
  const unmapped = useMemo(() => (markets.data ?? []).filter((m) => m.lat === null || m.lon === null), [markets.data]);

  if (countries.isError) return <ErrorState error={countries.error} what="countries" />;

  return (
    <div>
      <PageHeader
        title="Global explorer"
        lede="Find markets with price data, see how complete each series is, and check whether it can support a forecast. Points are individual markets; national statistics are not mapped."
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Field label="Country" htmlFor="f-country">
          <Select
            id="f-country"
            value={country}
            onChange={(v) => set({ country: v, commodity: null, market: null, series: null })}
            options={(countries.data ?? []).map((c) => ({ value: c.iso3, label: `${c.name} (${c.n_markets} markets)` }))}
            placeholder="Choose a country"
          />
        </Field>
        <Field label="Commodity" htmlFor="f-commodity">
          <Select
            id="f-commodity"
            value={commodity}
            onChange={(v) => set({ commodity: v, series: null })}
            options={(commodities.data ?? []).map((c) => ({ value: c.code, label: c.name }))}
            placeholder="All commodities"
          />
        </Field>
        <Field label="Market" htmlFor="f-market">
          <Select
            id="f-market"
            value={marketId}
            onChange={(v) => set({ market: v, series: null })}
            options={(markets.data ?? []).map((m) => ({ value: m.id, label: `${m.name}${m.eligible_series ? "" : " (no eligible series)"}` }))}
            placeholder={markets.isLoading ? "Loading…" : "Choose a market"}
          />
        </Field>
        <Field label="From" htmlFor="f-from">
          <input id="f-from" type="month" className={inputClass} value={from} onChange={(e) => set({ from: e.target.value })} />
        </Field>
        <Field label="To" htmlFor="f-to">
          <input id="f-to" type="month" className={inputClass} value={to} onChange={(e) => set({ to: e.target.value })} />
        </Field>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div>
          {markets.isLoading ? (
            <Loading label="Loading markets" />
          ) : markets.isError ? (
            <ErrorState error={markets.error} what="markets" />
          ) : (
            <MarketMap markets={markets.data ?? []} selected={marketId} onSelect={(id) => set({ market: id, series: null })} />
          )}
          {unmapped.length > 0 && (
            <p className="mt-2 text-sm text-ink-3">
              Not mapped (no coordinates in the source, so no market-local weather):{" "}
              {unmapped.map((m, i) => (
                <button key={m.id} type="button" className="underline-offset-2 hover:underline" onClick={() => set({ market: m.id, series: null })}>
                  {m.name}
                  {i < unmapped.length - 1 ? ", " : ""}
                </button>
              ))}
            </p>
          )}
        </div>

        <Panel title={market ? market.name : "Select a market"} note={market ? [market.admin1, market.admin2].filter(Boolean).join(", ") || undefined : "Click a point on the map."}>
          {!market && <Empty>Each point is a market where WFP reports prices. Filled points have at least one series long and complete enough to forecast.</Empty>}
          {market && series.isLoading && <Loading label="Loading series" />}
          {market && series.isError && <ErrorState error={series.error} what="series" />}
          {market && marketSeries.length > 0 && (
            <div className="space-y-4">
              <div>
                <label htmlFor="f-series" className="text-xs font-medium text-ink-3">
                  Price series (commodity · unit · price type)
                </label>
                <Select
                  id="f-series"
                  className="mt-1 w-full"
                  value={selectedSeries?.series_id ?? ""}
                  onChange={(v) => set({ series: v })}
                  options={marketSeries.map((s) => ({ value: s.series_id, label: `${s.commodity_name} · ${s.unit} · ${s.price_type} · ${s.currency}${s.eligible ? "" : " (not eligible)"}` }))}
                />
              </div>
              {selectedSeries && (
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <div className="text-xs text-ink-3">Observed months</div>
                    <div className="text-ink">{selectedSeries.n_observations}</div>
                  </div>
                  <div>
                    <div className="text-xs text-ink-3">Coverage</div>
                    <div className="text-ink">{pct(selectedSeries.coverage)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-ink-3">Span</div>
                    <div className="text-ink">
                      {month(selectedSeries.first_period)} – {month(selectedSeries.last_period)}
                    </div>
                  </div>
                </div>
              )}
              {selectedSeries && (
                <div>
                  {selectedSeries.eligible ? (
                    <Tag tone="good">Eligible for forecasting</Tag>
                  ) : (
                    <Note tone="warn">
                      Not eligible: {selectedSeries.reasons.join("; ")}.
                    </Note>
                  )}
                </div>
              )}
              {prices.isLoading && <Loading label="Loading prices" />}
              {prices.data && <PriceChart data={prices.data} start={from ? `${from}-01` : undefined} end={to ? `${to}-01` : undefined} height={230} />}
              {selectedSeries && (
                <Link className="inline-block text-sm font-medium text-rain hover:underline" href={`/market?series=${selectedSeries.series_id}`}>
                  Open the full market analysis
                </Link>
              )}
            </div>
          )}
          {market && !series.isLoading && marketSeries.length === 0 && <Empty>No price series match the current filters.</Empty>}
        </Panel>
      </div>

      {market && (
        <Panel className="mt-5" title="Weather near this market" note="NASA POWER grid cell containing the market (~50 km). A geographic proxy, not where the food was grown.">
          {!market.weather_location_id && <Empty>This market has no coordinates, so no market-local weather can be attached.</Empty>}
          {weather.isLoading && <Loading label="Loading weather" />}
          {weather.isError && <ErrorState error={weather.error} what="weather" />}
          {weather.data && <WeatherChart data={weather.data} start={from ? `${from}-01` : "2010-01-01"} end={to ? `${to}-01` : undefined} />}
        </Panel>
      )}
    </div>
  );
}
