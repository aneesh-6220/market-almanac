"use client";

import Link from "next/link";
import { useMemo } from "react";

import { baseOption, Chart, usePalette } from "@/components/chart";
import { PriceChart, WeatherChart } from "@/components/series-charts";
import { Empty, ErrorState, Loading, Note, PageHeader, Panel, Stat, Tag } from "@/components/ui";
import { download, fmt, month, pct, toCsv } from "@/lib/format";
import { useAgriculture, useCommodities, useIndicators, useLags, useMarkets, usePrices, useQuality, useWeather } from "@/lib/queries";
import { useUrlState } from "@/lib/url-state";

export function MarketClient() {
  const { get } = useUrlState();
  const seriesId = get("series");
  const prices = usePrices(seriesId || undefined);
  const quality = useQuality({ series_id: seriesId || undefined });
  const q = quality.data?.series.find((s) => s.series_id === seriesId);
  const first = prices.data?.items[0];
  const country = q?.country_iso3;
  const markets = useMarkets(country);
  const market = markets.data?.find((m) => m.market_code === q?.market_code || m.name === first?.market_name);
  const weather = useWeather(market?.weather_location_id);
  const lags = useLags(market?.weather_location_id ? seriesId : undefined);
  const indicators = useIndicators(country);
  const commodities = useCommodities(country);
  const fao = commodities.data?.find((c) => c.code === q?.commodity_code)?.fao_item_code;
  const agri = useAgriculture(country, fao);
  const extremes = (quality.data?.extremes ?? []).filter((e) => e.series_id === seriesId).map((e) => ({ period: String(e.period), classification: String(e.classification) }));
  const p = usePalette();

  const changeOption = useMemo(() => {
    if (!p || !prices.data) return null;
    const it = prices.data.items;
    const pts = it.slice(1).map((d, i) => {
      const prev = it[i];
      const ok = d.price && prev.price && new Date(d.period).getUTCMonth() === (new Date(prev.period).getUTCMonth() + 1) % 12;
      return [d.period, ok ? Math.log((d.price as number) / (prev.price as number)) * 100 : null];
    });
    const b = baseOption(p);
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => (v == null ? "gap" : `${v.toFixed(1)}%`) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", name: "log change, %" },
      series: [{ name: "Monthly change", type: "bar", data: pts, itemStyle: { color: (x: { value: [string, number] }) => (x.value[1] >= 0 ? p.grain : p.rain) }, barMaxWidth: 5 }],
    };
  }, [p, prices.data]);

  const lagOption = useMemo(() => {
    if (!p || !lags.data) return null;
    const b = baseOption(p);
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), trigger: "item", formatter: (x: { data: number; name: string }) => `Lag ${x.name} months: r = ${fmt(x.data)}` },
      xAxis: { ...(b.xAxis as object), type: "category", name: "rain anomaly lag (months)", nameLocation: "middle", nameGap: 26, data: lags.data.items.map((d) => String(d.lag_months)) },
      yAxis: { ...(b.yAxis as object), type: "value", min: -0.5, max: 0.5, name: "correlation" },
      series: [{ type: "bar", data: lags.data.items.map((d) => d.correlation), itemStyle: { color: p.rain }, barMaxWidth: 28 }],
    };
  }, [p, lags.data]);

  const macroOption = useMemo(() => {
    if (!p || !indicators.data) return null;
    const pick = (code: string) => indicators.data.items.filter((d) => d.indicator_code === code && d.value !== null);
    const yoy = (rows: { period: string; value: number | null }[]) => {
      const m = new Map(rows.map((r) => [r.period.slice(0, 7), r.value as number]));
      return rows.map((r) => {
        const d = new Date(r.period);
        const prev = `${d.getUTCFullYear() - 1}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
        return [r.period, m.has(prev) ? (Math.log((r.value as number) / (m.get(prev) as number)) * 100) : null];
      });
    };
    const cpi = yoy(pick("IMF.CPI.ALL"));
    const food = yoy(pick("IMF.CPI.FOOD"));
    const fx = yoy(pick("IMF.FX.USD"));
    if (!cpi.length && !fx.length) return null;
    const b = baseOption(p);
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => (v == null ? "—" : `${v.toFixed(1)}%`) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", name: "12-month log change, %" },
      series: [
        { name: "CPI, all items", type: "line", showSymbol: false, data: cpi, lineStyle: { color: p.ink2 } },
        { name: "CPI, food", type: "line", showSymbol: false, data: food, lineStyle: { color: p.grain } },
        { name: "LCU per USD", type: "line", showSymbol: false, data: fx, lineStyle: { color: p.rain, type: "dashed" } },
      ],
    };
  }, [p, indicators.data]);

  const agriOption = useMemo(() => {
    if (!p || !agri.data?.items.length) return null;
    const prod = agri.data.items.filter((d) => d.element_code === "5510");
    const yld = agri.data.items.filter((d) => d.element_code === "5412");
    const b = baseOption(p);
    return {
      ...b,
      grid: { ...(b.grid as object), right: 60 },
      xAxis: { ...(b.xAxis as object), type: "category", data: prod.map((d) => String(d.year)) },
      yAxis: [
        { ...(b.yAxis as object), type: "value", name: "production (t)" },
        { ...(b.yAxis as object), type: "value", name: "yield (kg/ha)", splitLine: { show: false } },
      ],
      series: [
        { name: "Production", type: "bar", data: prod.map((d) => d.value), itemStyle: { color: p.grainSoft, borderColor: p.grain } },
        { name: "Yield", type: "line", yAxisIndex: 1, data: yld.map((d) => d.value), lineStyle: { color: p.good }, itemStyle: { color: p.good } },
      ],
    };
  }, [p, agri.data]);

  if (!seriesId) return <Empty>Choose a series from the <Link className="underline" href="/explorer">explorer</Link>.</Empty>;
  if (prices.isError) return <ErrorState error={prices.error} what="prices" />;
  if (prices.isLoading || !first) return <Loading label="Loading market" />;

  return (
    <div>
      <PageHeader
        title={`${first.commodity_name} in ${first.market_name}`}
        lede={`${first.price_type} price, ${first.currency} per ${first.unit}. One comparable series: other units, price types or currencies are kept separate.`}
      >
        <button
          type="button"
          className="h-9 rounded border border-line px-3 text-sm text-ink hover:bg-surface-2"
          onClick={() => download(`shocktrace_${seriesId}_prices.csv`, toCsv(prices.data!.items))}
        >
          Download prices (CSV)
        </button>
        <Link className="inline-flex h-9 items-center rounded bg-ink px-3 text-sm text-bg" href={`/forecasts?series=${seriesId}`}>
          Open forecast
        </Link>
      </PageHeader>

      {q && (
        <div className="mb-6 grid grid-cols-2 gap-5 rounded-md border border-line bg-surface p-5 md:grid-cols-5">
          <Stat label="Observed months" value={q.n_observations} />
          <Stat label="Coverage of span" value={pct(q.coverage)} />
          <Stat label="Longest gap" value={`${q.longest_gap_months} months`} />
          <Stat label="Span" value={`${month(q.first_period)} – ${month(q.last_period)}`} />
          <div>
            <div className="text-xs text-ink-3">Forecasting</div>
            <div className="mt-1">{q.eligible ? <Tag tone="good">Eligible</Tag> : <Tag tone="warn">Not eligible</Tag>}</div>
          </div>
          {!q.eligible && <div className="col-span-full"><Note tone="warn">{q.reasons.join("; ")}.</Note></div>}
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
        <Panel title="Price history" note={`Source reference: ${first.source_ref ?? "—"} · retrieved ${first.retrieved_at?.slice(0, 10) ?? "—"}. Red points: flagged extreme moves (kept, not removed).`}>
          <PriceChart data={prices.data!} height={340} extremes={extremes} />
          {extremes.length > 0 && (
            <ul className="mt-2 text-sm text-ink-2">
              {extremes.map((e) => (
                <li key={e.period}>
                  {month(e.period)}: {e.classification.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Month-on-month change" note="Bars are omitted where a month is missing; gaps are never interpolated.">
            <Chart option={changeOption} height={240} ariaLabel="Monthly log price changes" />
          </Panel>
          <Panel title="Lagged relationship with rainfall" note={lags.data?.caveat ?? "Correlation of monthly price change at t with rainfall anomaly at t − k."}>
            {lags.isError && <Empty>No market-local weather is available for this series.</Empty>}
            {lags.isLoading && <Loading />}
            {lags.data && <Chart option={lagOption} height={240} ariaLabel="Correlation by lag between rainfall anomaly and price change" />}
          </Panel>
        </div>

        <Panel title="Weather near the market" note={weather.data?.proxy_warning ?? "NASA POWER grid cell containing the market."}>
          {weather.isLoading && <Loading />}
          {(weather.isError || !market?.weather_location_id) && !weather.isLoading && <Empty>No weather is stored for this market.</Empty>}
          {weather.data && (
            <>
              <WeatherChart data={weather.data} start={first.period} height={280} />
              <p className="mt-2 text-xs text-ink-3">
                Grid cell {weather.data.location_id} · anomalies use an {weather.data.climatology}.
              </p>
            </>
          )}
        </Panel>

        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Inflation and exchange-rate context" note="IMF monthly CPI and exchange rate for the country (national, not market-level).">
            {indicators.isLoading && <Loading />}
            {macroOption ? <Chart option={macroOption} height={250} ariaLabel="Consumer price inflation and exchange-rate change" /> : !indicators.isLoading && <Empty>No monthly macro data ingested for this country.</Empty>}
          </Panel>
          <Panel title="National production of the related crop" note="FAOSTAT annual, national totals. Not the supply origin of this market.">
            {agriOption ? <Chart option={agriOption} height={250} ariaLabel="Annual crop production and yield" /> : <Empty>{fao ? "No FAOSTAT data ingested for this crop." : "No related FAOSTAT crop is mapped for this commodity."}</Empty>}
          </Panel>
        </div>
      </div>
    </div>
  );
}
