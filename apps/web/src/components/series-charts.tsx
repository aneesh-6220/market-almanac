"use client";

import { useMemo } from "react";

import type { PricePage, Weather } from "@/lib/api";

import { baseOption, Chart, usePalette } from "./chart";

export function PriceChart({ data, start, end, height = 300, extremes }: { data: PricePage; start?: string; end?: string; height?: number; extremes?: { period: string; classification: string }[] }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const items = data.items.filter((d) => (!start || d.period >= start) && (!end || d.period <= end));
    const first = data.items[0];
    const base = baseOption(p);
    return {
      ...base,
      grid: { ...(base.grid as object), bottom: 60 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (v: number) => (v == null ? "missing" : `${v.toFixed(2)} ${first?.currency}/${first?.unit}`) },
      xAxis: { ...(base.xAxis as object), type: "time" },
      yAxis: { ...(base.yAxis as object), type: "value", scale: true, name: first ? `${first.currency} per ${first.unit}` : "" },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, borderColor: p.line, textStyle: { color: p.ink3 } }],
      series: [
        {
          name: "Price",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          lineStyle: { color: p.grain, width: 2 },
          itemStyle: { color: p.grain },
          data: items.map((d) => [d.period, d.price]),
          markPoint: extremes?.length
            ? {
                symbol: "circle",
                symbolSize: 9,
                label: { show: false },
                itemStyle: { color: p.bad },
                data: extremes
                  .map((e) => {
                    const hit = items.find((d) => d.period === e.period);
                    return hit ? { coord: [hit.period, hit.price], name: e.classification.replace("_", " ") } : null;
                  })
                  .filter(Boolean),
              }
            : undefined,
        },
      ],
    };
  }, [p, data, start, end, extremes]);
  return <Chart option={option} height={height} ariaLabel="Monthly price history" />;
}

export function WeatherChart({ data, start, end, height = 260 }: { data: Weather; start?: string; end?: string; height?: number }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const items = data.items.filter((d) => (!start || d.period >= start) && (!end || d.period <= end));
    const base = baseOption(p);
    return {
      ...base,
      grid: { ...(base.grid as object), right: 56 },
      xAxis: { ...(base.xAxis as object), type: "time" },
      yAxis: [
        { ...(base.yAxis as object), type: "value", name: "mm / month" },
        { ...(base.yAxis as object), type: "value", name: "anomaly (s.d.)", splitLine: { show: false }, min: -4, max: 4 },
      ],
      series: [
        { name: "Rainfall", type: "bar", data: items.map((d) => [d.period, d.precip_total_mm]), itemStyle: { color: p.rainSoft, borderColor: p.rain, borderWidth: 0.5 }, barMaxWidth: 6 },
        { name: "Rainfall anomaly", type: "line", yAxisIndex: 1, showSymbol: false, data: items.map((d) => [d.period, d.rain_anomaly_z]), lineStyle: { color: p.rain, width: 1.5 } },
        { name: "Temperature anomaly", type: "line", yAxisIndex: 1, showSymbol: false, data: items.map((d) => [d.period, d.temp_anomaly_z]), lineStyle: { color: p.heat, width: 1.2, type: "dashed" } },
      ],
    };
  }, [p, data, start, end]);
  return <Chart option={option} height={height} ariaLabel="Monthly rainfall and temperature anomalies near the market" />;
}
