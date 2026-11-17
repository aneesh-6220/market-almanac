"use client";

import { BarChart, CustomChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

echarts.use([
  LineChart, BarChart, ScatterChart, CustomChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent, VisualMapComponent, CanvasRenderer,
]);

export type Palette = Record<"ink" | "ink2" | "ink3" | "line" | "surface" | "rain" | "grain" | "heat" | "good" | "warn" | "neutral" | "bad" | "rainSoft" | "grainSoft", string>;

function readPalette(): Palette {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    ink: v("--ink"), ink2: v("--ink-2"), ink3: v("--ink-3"), line: v("--line"), surface: v("--surface"),
    rain: v("--rain"), grain: v("--grain"), heat: v("--heat"), good: v("--good"), warn: v("--warn"),
    neutral: v("--neutral"), bad: v("--bad"), rainSoft: v("--rain-soft"), grainSoft: v("--grain-soft"),
  };
}

/** Re-reads CSS tokens whenever the theme changes so charts match light/dark mode. */
export function usePalette(): Palette | null {
  const [p, setP] = useState<Palette | null>(null);
  useEffect(() => {
    const update = () => setP(readPalette());
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => {
      mo.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);
  return p;
}

export function baseOption(p: Palette): echarts.EChartsCoreOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "var(--font-plex), system-ui, sans-serif", color: p.ink2 },
    grid: { left: 56, right: 20, top: 30, bottom: 36, containLabel: false },
    tooltip: {
      trigger: "axis",
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.ink, fontSize: 12 },
      confine: true,
    },
    legend: { top: 0, right: 0, textStyle: { color: p.ink2, fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    xAxis: { axisLine: { lineStyle: { color: p.line } }, axisLabel: { color: p.ink3 }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, axisLabel: { color: p.ink3 }, splitLine: { lineStyle: { color: p.line, type: "dashed" } }, nameTextStyle: { color: p.ink3 } },
  };
}

export function Chart({
  option,
  height = 300,
  ariaLabel,
  onClick,
}: {
  option: echarts.EChartsCoreOption | null;
  height?: number;
  ariaLabel: string;
  onClick?: (params: unknown) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      inst.current?.dispose();
      inst.current = null;
    };
  }, []);
  useEffect(() => {
    if (inst.current && option) inst.current.setOption({ aria: { enabled: true }, ...option }, { notMerge: true });
  }, [option]);
  useEffect(() => {
    const i = inst.current;
    if (!i || !onClick) return;
    i.on("click", onClick);
    return () => {
      i.off("click", onClick);
    };
  }, [onClick]);
  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />;
}
