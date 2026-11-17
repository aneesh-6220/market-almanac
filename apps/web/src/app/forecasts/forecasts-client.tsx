"use client";

import Link from "next/link";
import { useEffect, useMemo } from "react";

import { baseOption, Chart, usePalette } from "@/components/chart";
import { Empty, ErrorState, Field, Loading, Note, PageHeader, Panel, Select, Stat, Tag } from "@/components/ui";
import type { Forecast } from "@/lib/api";
import { fmt, modelLabel, month, pct } from "@/lib/format";
import { useExperiments, useForecasts, usePredictions, usePrices } from "@/lib/queries";
import { useUrlState } from "@/lib/url-state";

const VALIDATION: Record<string, { label: string; tone: "good" | "neutral" | "warn" | "muted"; help: string }> = {
  validated_outperforms_baseline: {
    label: "Beat its baseline out of sample",
    tone: "good",
    help: "In the rolling backtest this model had significantly lower loss than the simple baseline.",
  },
  validated_no_better_than_baseline: {
    label: "No better than its baseline",
    tone: "neutral",
    help: "In the rolling backtest this model did not significantly beat the simple baseline. Treat it as no more informative than the baseline.",
  },
  insufficient_validation: {
    label: "Too little validation",
    tone: "warn",
    help: "There were too few out-of-sample periods or events to judge this model.",
  },
  not_evaluated: { label: "Not evaluated", tone: "muted", help: "This model was not backtested." },
};

function ValidationTag({ status }: { status: string }) {
  const v = VALIDATION[status] ?? { label: status, tone: "muted" as const };
  return <Tag tone={v.tone}>{v.label}</Tag>;
}

export function ForecastsClient() {
  const { get, set } = useUrlState();
  const exps = useExperiments();
  const expId = get("experiment") || exps.data?.[0]?.id || "";
  const forecasts = useForecasts({ experiment_id: expId || undefined });
  const seriesOptions = useMemo(() => {
    const seen = new Map<string, Forecast>();
    for (const f of forecasts.data ?? []) if (!seen.has(f.series_id)) seen.set(f.series_id, f);
    return [...seen.values()];
  }, [forecasts.data]);
  const seriesId = get("series") || seriesOptions[0]?.series_id || "";

  useEffect(() => {
    if (get("series") && forecasts.data && !seriesOptions.some((s) => s.series_id === get("series")) && seriesOptions.length) {
      set({ series: seriesOptions[0].series_id });
    }
  }, [forecasts.data, seriesOptions, get, set]);

  const { mine, reg, clf } = useMemo(() => {
    const all = (forecasts.data ?? []).filter((f) => f.series_id === seriesId);
    const byH = (task: string) => all.filter((f) => f.task === task).sort((a, b) => a.horizon - b.horizon);
    return { mine: all, reg: byH("regression"), clf: byH("classification") };
  }, [forecasts.data, seriesId]);
  const prices = usePrices(seriesId || undefined);
  const backtest = usePredictions({ experiment_id: expId || undefined, task: "regression", horizon: 1, series_id: seriesId || undefined, models: "naive,ridge_A,ridge_B" });
  const p = usePalette();
  const head = mine[0]?.payload as Record<string, unknown> | undefined;
  const exp = exps.data?.find((e) => e.id === expId);

  const fanOption = useMemo(() => {
    if (!p || !prices.data) return null;
    const hist = prices.data.items.slice(-48).map((d) => [d.period, d.price]);
    const issued = reg.filter((f) => f.status === "issued");
    const last = prices.data.items.at(-1);
    const pts = (k: string) => [[last?.period, last?.price], ...issued.map((f) => [f.target_period, f.payload[k] as number])];
    const b = baseOption(p);
    const band = (lowK: string, highK: string, color: string, name: string) => [
      { name, type: "line", stack: name, symbol: "none", lineStyle: { opacity: 0 }, data: pts(lowK), tooltip: { show: false } },
      {
        name,
        type: "line",
        stack: name,
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color, opacity: 1 },
        data: pts(highK).map((d, i) => [d[0], (d[1] as number) - ((pts(lowK)[i][1] as number) ?? 0)]),
        tooltip: { show: false },
      },
    ];
    return {
      ...b,
      legend: { ...(b.legend as object), data: ["Observed price", "Point forecast", "95% interval", "80% interval"] },
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => (v == null ? "missing" : v.toFixed(2)) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", scale: true, name: last ? `${last.currency} per ${last.unit}` : "" },
      series: [
        ...(issued.length ? band("lower95", "upper95", p.rainSoft, "95% interval") : []),
        ...(issued.length ? band("lower80", "upper80", p.rain + "55", "80% interval") : []),
        { name: "Observed price", type: "line", showSymbol: false, data: hist, lineStyle: { color: p.grain, width: 2 }, itemStyle: { color: p.grain } },
        ...(issued.length
          ? [{ name: "Point forecast", type: "line", data: pts("point_price"), lineStyle: { color: p.rain, type: "dashed", width: 2 }, itemStyle: { color: p.rain }, symbolSize: 6 }]
          : []),
      ],
    };
  }, [p, prices.data, reg]);

  const backtestOption = useMemo(() => {
    if (!p || !backtest.data?.items.length) return null;
    const by = (m: string) => backtest.data.items.filter((d) => d.model === m);
    const actual = by("naive").map((d) => [d.target_period, d.y === null ? null : d.y * 100]);
    const line = (m: string, color: string, dashed = false) => ({
      name: modelLabel(m),
      type: "line",
      showSymbol: false,
      data: by(m).map((d) => [d.target_period, d.pred === null ? null : d.pred * 100]),
      lineStyle: { color, width: 1.6, type: dashed ? "dashed" : "solid" },
      itemStyle: { color },
    });
    const b = baseOption(p);
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => (v == null ? "—" : `${v.toFixed(1)}%`) },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", name: "1-month log change, %" },
      dataZoom: [{ type: "inside" }],
      series: [
        { name: "Actual", type: "bar", data: actual, itemStyle: { color: p.ink3, opacity: 0.45 }, barMaxWidth: 4 },
        line("ridge_A", p.ink3, true),
        line("ridge_B", p.rain),
      ],
    };
  }, [p, backtest.data]);

  if (exps.isError) return <ErrorState error={exps.error} what="experiments" />;
  if (exps.isLoading) return <Loading label="Loading experiments" />;
  if (!exps.data?.length) return <Empty>No experiments yet. Run <code className="code">make demo</code> or <code className="code">shocktrace backtest</code> first.</Empty>;

  return (
    <div>
      <PageHeader
        title="Forecast explorer"
        lede="The latest forecast for each series, with intervals taken from the model's own out-of-sample errors and a plain statement of whether the model has earned trust in backtesting."
      />
      <div className="mb-6 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Field label="Experiment" htmlFor="fc-exp">
          <Select id="fc-exp" value={expId} onChange={(v) => set({ experiment: v, series: null })} options={exps.data.map((e) => ({ value: e.id, label: `${e.name}${e.synthetic ? " (synthetic)" : ""}` }))} />
        </Field>
        <Field label="Series" htmlFor="fc-series">
          <Select
            id="fc-series"
            value={seriesId}
            onChange={(v) => set({ series: v })}
            options={seriesOptions.map((f) => ({ value: f.series_id, label: `${String(f.payload.market_name ?? f.series_id)} · ${String(f.payload.commodity_name ?? "")}` }))}
            placeholder={forecasts.isLoading ? "Loading…" : "Choose a series"}
          />
        </Field>
      </div>

      {forecasts.isError && <ErrorState error={forecasts.error} what="forecasts" />}
      {forecasts.data && !forecasts.data.length && <Empty>This experiment produced no forward forecasts.</Empty>}

      {head && (
        <>
          <div className="mb-6 rounded-md border border-line bg-surface p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="font-serif text-2xl text-ink">
                {String(head.commodity_name)} in {String(head.market_name)}
              </h2>
              <Link href={`/market?series=${seriesId}`} className="text-sm text-rain underline-offset-4 hover:underline">
                Open market analysis
              </Link>
            </div>
            <p className="mt-1 text-sm text-ink-3">
              Information cut-off {month(mine[0].information_cutoff)} · last observed price {fmt(head.last_price as number, 4)} {String(head.currency)}/{String(head.unit)}
              {prices.data?.items.length ? ` (observed for ${month(prices.data.items.at(-1)!.period)})` : ""}
              {exp?.synthetic && <span className="synthetic-band ml-2 rounded px-1.5 text-ink">synthetic</span>}
            </p>
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              {reg.map((f) => (
                <div key={f.id} className="border-t border-line pt-4">
                  <div className="text-sm text-ink-3">
                    Price in {month(f.target_period)} · {f.horizon}-month horizon · {modelLabel(f.model)}
                  </div>
                  {f.status === "issued" ? (
                    <>
                      <div className="mt-1 text-3xl font-medium tabular-nums text-ink">{fmt(f.payload.point_price as number, 4)}</div>
                      <div className="text-sm tabular-nums text-ink-2">
                        80%: {fmt(f.payload.lower80 as number, 4)}–{fmt(f.payload.upper80 as number, 4)} · 95%: {fmt(f.payload.lower95 as number, 4)}–{fmt(f.payload.upper95 as number, 4)}
                      </div>
                      {typeof head.last_price === "number" && (
                        <div className="mt-1 text-sm tabular-nums text-ink-2" data-testid="naive-benchmark">
                          No-change benchmark: {fmt(head.last_price, 4)}
                          {f.validation_status !== "validated_outperforms_baseline" && " (this model has not shown it does better)"}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="mt-1 text-ink-2">Withheld: {f.reason}</div>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <ValidationTag status={f.validation_status} />
                    <span className="text-xs text-ink-3">{f.reason}</span>
                  </div>
                </div>
              ))}
              {clf.map((f) => (
                <div key={f.id} className="border-t border-line pt-4">
                  <div className="text-sm text-ink-3">
                    Chance of a rise of {pct(f.payload.threshold as number)} or more by {month(f.target_period)} · {modelLabel(f.model)}
                  </div>
                  {f.status === "issued" ? (
                    <div className="mt-1 text-3xl font-medium tabular-nums text-ink">{pct(f.payload.probability as number, 1)}</div>
                  ) : (
                    <div className="mt-1 text-ink-2">Withheld: {f.reason}</div>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <ValidationTag status={f.validation_status} />
                    {typeof f.payload.decision_threshold === "number" && <span className="text-xs text-ink-3">alert threshold {pct(f.payload.decision_threshold, 1)}</span>}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5">
              <Note>
                {VALIDATION[reg[0]?.validation_status ?? ""]?.help} Intervals are empirical quantiles of this model&apos;s backtest residuals; they assume future errors resemble past ones. A forecast is not a statement that weather caused, or will cause, any price change.
              </Note>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
            <Panel title="Recent prices and the forecast" note="Shaded bands: 80% and 95% prediction intervals.">
              {prices.isLoading ? <Loading /> : <Chart option={fanOption} height={340} ariaLabel="Recent prices with forecast and prediction intervals" />}
            </Panel>
            <Panel
              title="How this model did in the rolling backtest"
              note="Each prediction was made using only data available at its origin month. Bars are what actually happened; lines are one-month-ahead predictions."
              actions={<Link href={`/lab?experiment=${expId}`} className="text-sm text-rain underline-offset-4 hover:underline">Compare all models</Link>}
            >
              {backtest.isLoading && <Loading />}
              {backtest.isError && <ErrorState error={backtest.error} what="backtest predictions" />}
              {backtestOption ? <Chart option={backtestOption} height={280} ariaLabel="Backtest predictions against actual monthly price changes" /> : !backtest.isLoading && <Empty>No backtest predictions are stored for this series.</Empty>}
            </Panel>
            <div className="grid grid-cols-2 gap-5 rounded-md border border-line bg-surface p-5 md:grid-cols-4">
              <Stat label="Forecast origin" value={month(mine[0].origin_period)} />
              <Stat label="Experiment" value={<span className="block break-all font-mono text-xs">{expId}</span>} />
              <Stat label="Interval method" value={<span className="text-sm">Empirical residual quantiles</span>} />
              <Stat label="Mode" value={exp?.mode ?? "—"} hint={exp?.synthetic ? "synthetic demo data" : "observed data"} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
