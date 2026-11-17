"use client";

import type { Comparison } from "@/lib/api";
import { fmt, modelLabel, pValue, VERDICT } from "@/lib/format";

/**
 * Loss-ratio forest plot. Each row is one comparison: the enhanced model's mean loss divided
 * by the comparison model's (B / A). Left of 1.0 means B forecast better. The bar is the 95%
 * moving-block bootstrap interval; the dot is the point estimate.
 */
export function ForestPlot({ rows, compact = false }: { rows: Comparison[]; compact?: boolean }) {
  const vals = rows.flatMap((r) => [r.bootstrap_loss_ratio.ci_low, r.bootstrap_loss_ratio.ci_high, r.relative_loss_b_vs_a]);
  const finite = vals.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const lo = Math.min(0.5, ...finite.map((v) => v - 0.05));
  const hi = Math.max(1.5, ...finite.map((v) => v + 0.05));
  const x = (v: number) => ((Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * 100;
  const ticks = [0.5, 0.75, 1, 1.25, 1.5].filter((t) => t >= lo && t <= hi);
  const color = (v: string) =>
    v === "improved" ? "var(--good)" : v === "inconsistent" ? "var(--warn)" : v === "insufficient_evidence" ? "var(--ink-3)" : "var(--neutral)";
  return (
    <figure className="w-full" aria-label="Forest plot of loss ratios between model pairs">
      <div
        className={
          compact
            ? "grid grid-cols-[minmax(0,1fr)_7.5rem] gap-x-4 gap-y-0.5"
            : "grid grid-cols-[minmax(0,1fr)] gap-y-1 md:grid-cols-[minmax(10rem,15rem)_minmax(0,1fr)_minmax(6.5rem,auto)] md:gap-x-4"
        }
      >
        {!compact && <div className="hidden text-xs text-ink-3 md:block">Comparison</div>}
        <div className={compact ? "relative h-4" : "relative hidden h-4 md:block"}>
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2 text-xs text-ink-3" style={{ left: `${x(t)}%` }}>
              {t === 1 ? "1.0" : t}
            </span>
          ))}
        </div>
        <div className={compact ? "text-right text-xs text-ink-3" : "hidden text-right text-xs text-ink-3 md:block"}>p (B better)</div>
        {rows.map((r, i) => {
          const b = r.bootstrap_loss_ratio;
          const point = r.relative_loss_b_vs_a;
          const label = `${r.task === "regression" ? "Price change" : "Spike risk"} · ${r.horizon}m`;
          return (
            <div key={i} className="contents">
              <div className={compact ? "col-span-2 pt-3 text-sm" : "pt-2 text-sm md:pt-0"}>
                <div className="text-ink">{compact ? label : `${modelLabel(r.model_b)}`}</div>
                <div className="text-xs text-ink-3">{compact ? `${modelLabel(r.model_b)} vs ${modelLabel(r.model_a)}` : `vs ${modelLabel(r.model_a)} · ${label}`}</div>
              </div>
              <div className="relative h-9" title={`Loss ratio ${fmt(point)}; 95% CI ${fmt(b.ci_low)}–${fmt(b.ci_high)}`}>
                <div className="absolute inset-y-0 w-px bg-ink-3" style={{ left: `${x(1)}%` }} aria-hidden />
                {ticks.filter((t) => t !== 1).map((t) => (
                  <div key={t} className="absolute inset-y-2 w-px bg-line" style={{ left: `${x(t)}%` }} aria-hidden />
                ))}
                {typeof b.ci_low === "number" && typeof b.ci_high === "number" && (
                  <div
                    className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full opacity-45"
                    style={{ left: `${x(b.ci_low)}%`, width: `${Math.max(x(b.ci_high) - x(b.ci_low), 0.5)}%`, background: color(r.verdict) }}
                  />
                )}
                {typeof point === "number" && (
                  <div
                    className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
                    style={{ left: `${x(point)}%`, background: color(r.verdict) }}
                  />
                )}
              </div>
              <div className={compact ? "flex items-center justify-end gap-2 text-sm" : "flex items-center justify-between gap-2 pb-2 text-sm md:justify-end md:pb-0"}>
                <span className="tabular-nums text-ink-2">{pValue(r.dm.p_value_b_better)}</span>
                <span className="text-xs font-medium" style={{ color: color(r.verdict) }}>
                  {VERDICT[r.verdict]?.short ?? r.verdict}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <figcaption className="mt-3 text-xs text-ink-3">
        Ratio of mean out-of-sample loss (squared error, or Brier score for spikes), enhanced ÷ comparison model, on a log
        scale. Left of 1.0 means the enhanced model forecast better. Bars: 95% moving-block bootstrap intervals over origin
        months. p: one-sided Diebold–Mariano test with HAC variance and small-sample correction.
      </figcaption>
    </figure>
  );
}
