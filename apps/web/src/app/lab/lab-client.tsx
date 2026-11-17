"use client";

import { format as echartsFormat } from "echarts/core";
import { useMemo, useState } from "react";

import { baseOption, Chart, usePalette } from "@/components/chart";
import { ForestPlot } from "@/components/forest-plot";
import { Empty, ErrorState, Field, Loading, Note, PageHeader, Panel, Select, Tag, VerdictBadge } from "@/components/ui";
import { apiUrl, type Comparison, type Task } from "@/lib/api";
import { fmt, modelLabel, month, pct, pValue, VERDICT } from "@/lib/format";
import { StudyPanel } from "@/components/study-panel";
import { useExperiment, useExperiments } from "@/lib/queries";
import { useUrlState } from "@/lib/url-state";

const ROLES = [
  { id: "primary_production", label: "Production-region weather", help: "Price history plus production-region, crop-season weather (P) against price history alone (A), on identical rows." },
  { id: "production_vs_local", label: "Production vs market-local", help: "Production-region weather (P) against market-local weather (B), on identical rows." },
  { id: "secondary", label: "Macro and agriculture", help: "Does adding macro-economic (C) or agricultural (D) features help beyond weather?" },
  { id: "specification", label: "Other model types", help: "The same weather comparison with elastic net and gradient boosting, as a specification check." },
  { id: "vs_baseline", label: "Against simple baselines", help: "Does a fitted model beat the no-change forecast or the historical spike rate at all?" },
];

type Row = Record<string, unknown>;

function MetricsTable({ task }: { task: Task }) {
  const models = Object.entries(task.models ?? {}) as [string, Row][];
  const reg = task.task === "regression";
  const cols: [string, (m: Row) => string][] = reg
    ? [
        ["MAE", (m) => fmt(m.mae)],
        ["RMSE", (m) => fmt(m.rmse)],
        ["MAE vs naive", (m) => fmt(m.relative_mae)],
        ["Bias", (m) => fmt(m.bias, 2)],
        ["Direction right", (m) => pct(m.directional_accuracy)],
        ["80% coverage", (m) => pct((m.interval_coverage as Row | undefined)?.["80"] && ((m.interval_coverage as Record<string, Row>)["80"].empirical as number))],
      ]
    : [
        ["Brier", (m) => fmt(m.brier)],
        ["Brier skill", (m) => fmt(m.brier_skill, 2)],
        ["PR-AUC", (m) => fmt(m.pr_auc)],
        ["Precision", (m) => pct(m.precision)],
        ["Recall", (m) => pct(m.recall)],
        ["F1", (m) => fmt(m.f1, 2)],
      ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <caption className="sr-only">Out-of-sample metrics by model</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th scope="col" className="py-2 pr-3 font-medium">Model</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">n</th>
            {cols.map(([c]) => (
              <th key={c} scope="col" className="py-2 pr-3 text-right font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map(([name, m]) => (
            <tr key={name} className="border-b border-line/60 last:border-0">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink">{modelLabel(name)}</th>
              <td className="py-1.5 pr-3 text-right tabular-nums text-ink-3">{String(m.n ?? "—")}</td>
              {cols.map(([c, f]) => (
                <td key={c} className="py-1.5 pr-3 text-right tabular-nums text-ink-2">{f(m)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!reg && (
        <p className="mt-2 text-xs text-ink-3">
          {String((models[0]?.[1].positives as number) ?? "—")} spike events in {String(models[0]?.[1].n ?? "—")} test rows. Precision, recall and F1 use a decision threshold chosen on inner validation data only.
        </p>
      )}
    </div>
  );
}

function CalibrationChart({ task }: { task: Task }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const pick = (m: string) => (((task.models?.[m] as Row | undefined)?.calibration as Row[] | undefined) ?? []).filter((b) => !b.suppressed);
    const b = baseOption(p);
    const s = (m: string, color: string) => ({
      name: modelLabel(m),
      type: "line",
      data: pick(m).map((x) => [x.mean_predicted, x.observed_rate, x.count]),
      symbolSize: (v: number[]) => Math.max(5, Math.min(16, Math.sqrt(v[2]))),
      lineStyle: { color },
      itemStyle: { color },
    });
    return {
      ...b,
      tooltip: { trigger: "item", formatter: (x: { seriesName: string; value: number[] }) => `${echartsFormat.encodeHTML(x.seriesName)}<br/>predicted ${pct(x.value[0], 1)} · observed ${pct(x.value[1], 1)} · ${x.value[2]} rows` },
      xAxis: { ...(b.xAxis as object), type: "value", min: 0, max: 1, name: "predicted probability", nameLocation: "middle", nameGap: 26 },
      yAxis: { ...(b.yAxis as object), type: "value", min: 0, max: 1, name: "observed frequency" },
      series: [
        { name: "Perfect calibration", type: "line", data: [[0, 0], [1, 1]], symbol: "none", lineStyle: { color: p.line, type: "dashed" }, tooltip: { show: false } },
        s("logit_A", p.ink3),
        s("logit_B", p.rain),
      ],
    };
  }, [p, task]);
  return <Chart option={option} height={260} ariaLabel="Calibration of spike probabilities" />;
}

function SubperiodChart({ rows }: { rows: Comparison[] }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const b = baseOption(p);
    const cats = rows.map((r) => `${r.task === "regression" ? "Price" : "Spike"} ${r.horizon}m`);
    const half = (i: number) => rows.map((r) => {
      const v = r.subperiods[i]?.mean_diff;
      return v === null || v === undefined ? null : v / (r.mean_loss_a || 1);
    });
    return {
      ...b,
      tooltip: { ...(b.tooltip as object), valueFormatter: (v: number) => (v == null ? "—" : pct(v, 1)) },
      xAxis: { ...(b.xAxis as object), type: "category", data: cats },
      yAxis: { ...(b.yAxis as object), type: "value", name: "loss reduction vs A", axisLabel: { color: p.ink3, formatter: (v: number) => pct(v) } },
      series: [
        { name: "First half of test period", type: "bar", data: half(0), itemStyle: { color: p.rainSoft, borderColor: p.rain }, barMaxWidth: 22 },
        { name: "Second half", type: "bar", data: half(1), itemStyle: { color: p.rain }, barMaxWidth: 22 },
      ],
    };
  }, [p, rows]);
  return <Chart option={option} height={240} ariaLabel="Loss reduction by sub-period for primary comparisons" />;
}

function ImportanceChart({ items }: { items: Row[] }) {
  const p = usePalette();
  const option = useMemo(() => {
    if (!p) return null;
    const top = items.slice(0, 10).reverse();
    const b = baseOption(p);
    return {
      ...b,
      grid: { ...(b.grid as object), left: 150 },
      tooltip: { ...(b.tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { ...(b.xAxis as object), type: "value", name: "loss increase when shuffled", nameLocation: "middle", nameGap: 26 },
      yAxis: { ...(b.yAxis as object), type: "category", data: top.map((d) => String(d.feature)), axisLabel: { color: p.ink2 } },
      series: [{ type: "bar", data: top.map((d) => ({ value: d.importance_mean, itemStyle: { color: String(d.feature).startsWith("w_") ? p.rain : p.grain } })), barMaxWidth: 14 }],
    };
  }, [p, items]);
  return <Chart option={option} height={300} ariaLabel="Permutation importance of features" />;
}

export function LabClient() {
  const { get, set } = useUrlState();
  const exps = useExperiments();
  const expId = get("experiment") || exps.data?.[0]?.id || "";
  const detail = useExperiment(expId || undefined);
  const [roleChoice, setRole] = useState("");
  const r = detail.data?.results;
  const summary = detail.data?.summary;
  const tasks = r?.tasks ?? [];
  const all = tasks.flatMap((t) => t.comparisons);
  const role = roleChoice || ROLES.find((x) => all.some((c) => c.role === x.id))?.id || "vs_baseline";
  const comps = all.filter((c) => c.role === role);
  const primary = tasks.flatMap((t) => t.comparisons).filter((c) => c.role === "primary");
  const taskKey = get("task") || (tasks[0] ? `${tasks[0].task}:${tasks[0].horizon}` : "");
  const task = tasks.find((t) => `${t.task}:${t.horizon}` === taskKey) ?? tasks[0];
  const imp = (task?.permutation_importance ?? {}) as Record<string, Row[]>;
  const impModel = task?.task === "regression" ? "ridge_B" : "logit_B";
  const verdict = r?.conclusion?.verdict as string | undefined;

  if (exps.isError) return <ErrorState error={exps.error} what="experiments" />;
  if (exps.isLoading) return <Loading label="Loading experiments" />;
  if (!exps.data?.length) return <Empty>No experiments yet. Run <code className="code">make demo</code> or <code className="code">market-almanac backtest</code> first.</Empty>;

  return (
    <div>
      <PageHeader
        title="Research Lab"
        lede="The evidence behind every claim: the pre-registered study, each experiment's comparisons, how models were scored out of sample, and how much the results depend on a few observations."
      >
        {expId && (
          <>
            <a className="inline-flex h-9 items-center rounded border border-line px-3 text-sm text-ink hover:bg-surface-2" href={apiUrl(`/api/v1/reports/${expId}`)}>
              Report (Markdown)
            </a>
            <a className="inline-flex h-9 items-center rounded bg-ink px-3 text-sm text-bg" href={apiUrl(`/api/v1/exports/${expId}`, { format: "zip" })}>
              Download bundle
            </a>
          </>
        )}
      </PageHeader>

      <div className="mb-8">
        <StudyPanel />
      </div>

      <h2 className="mb-3 font-serif text-2xl text-ink">Individual experiments</h2>
      <p className="mb-4 max-w-3xl text-sm text-ink-2">
        One experiment is one country and commodity under one timing assumption. Runs replaced by a later method revision are kept but hidden from this list.
      </p>
      <div className="mb-6 max-w-xl">
        <Field label="Experiment" htmlFor="lab-exp">
          <Select id="lab-exp" value={expId} onChange={(v) => set({ experiment: v, task: null })} options={exps.data.map((e) => ({ value: e.id, label: `${e.name}${e.synthetic ? " (synthetic)" : ""}` }))} />
        </Field>
      </div>

      {detail.isLoading && <Loading label="Loading results" />}
      {detail.isError && <ErrorState error={detail.error} what="experiment results" />}

      {r && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
          <section className="min-w-0 rounded-md border border-line bg-surface p-5 md:p-7" aria-label="Conclusion">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictBadge verdict={verdict} />
              {r.synthetic && <span className="synthetic-band rounded px-1.5 text-sm text-ink">synthetic data</span>}
              <Tag tone={summary?.evidence_class === "confirmatory" ? "good" : "muted"}>{summary?.evidence_class ?? "exploratory"} evidence</Tag>
              <Tag>price lag {summary?.price_release_lag_months ?? 0} mo</Tag>
              <span className="text-sm text-ink-3">
                {r.data?.n_series as number} series · origins {month(r.data?.first_origin as string)}–{month(r.data?.last_origin as string)} · config {r.config_hash.slice(0, 10)}
              </span>
            </div>
            <p className="mt-3 max-w-3xl font-serif text-2xl leading-snug text-ink">{VERDICT[verdict ?? ""]?.label ?? "No verdict"}.</p>
            <p className="mt-1 max-w-3xl text-ink-2">{r.conclusion?.statement as string}</p>
            <div className="mt-6">{primary.length ? <ForestPlot rows={primary} /> : <Empty>No primary comparison had enough out-of-sample data.</Empty>}</div>
          </section>

          <Panel title="Supporting comparisons" note={ROLES.find((x) => x.id === role)?.help}>
            <div role="tablist" aria-label="Comparison group" className="mb-4 flex flex-wrap gap-1.5">
              {ROLES.map((x) => (
                <button
                  key={x.id}
                  role="tab"
                  type="button"
                  aria-selected={role === x.id}
                  onClick={() => setRole(x.id)}
                  className={`h-8 rounded px-3 text-sm ${role === x.id ? "bg-ink text-bg" : "border border-line text-ink-2 hover:bg-surface-2"}`}
                >
                  {x.label}
                </button>
              ))}
            </div>
            {comps.length ? <ForestPlot rows={comps} /> : <Empty>No comparisons of this kind were run (a feature family may have had no data).</Empty>}
            {comps.length > 0 && (
              <ul className="mt-4 space-y-1 text-sm text-ink-2">
                {comps.map((c, i) => (
                  <li key={i}>
                    <span className="text-ink">{modelLabel(c.model_b)}</span> vs {modelLabel(c.model_a)}, {c.task === "regression" ? "price change" : "spike"} {c.horizon}m: {c.reason} (n periods {c.dm.n_periods}, HAC lags {c.dm.lags}).
                    {c.influence?.fragile ? ` Depends on few observations: ${(c.influence.reasons ?? []).join("; ")}.` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {primary.length > 0 && (
            <Panel title="Is the improvement stable over time?" note="Share of the price-only model's loss removed by adding weather, in each half of the test period. A result that holds in only one half is reported as inconsistent.">
              <SubperiodChart rows={primary} />
            </Panel>
          )}

          <Panel
            title="Model scores"
            note="All metrics are out of sample, pooled over every series and origin month."
            actions={
              <Select
                id="lab-task"
                value={taskKey}
                onChange={(v) => set({ task: v })}
                options={tasks.map((t) => ({ value: `${t.task}:${t.horizon}`, label: `${t.task === "regression" ? "Price change" : "Spike"} · ${t.horizon} month${t.horizon > 1 ? "s" : ""} ahead` }))}
              />
            }
          >
            {task?.status && task.status !== "ok" ? <Note tone="warn">{task.reason ?? "This task could not be evaluated."}</Note> : task && <MetricsTable task={task} />}
          </Panel>

          {task && task.status === "ok" && (
            <div className="grid gap-5 lg:grid-cols-2">
              {task.task === "classification" ? (
                <Panel title="Calibration" note="Do predicted spike probabilities match how often spikes happened? Sparse bins are hidden.">
                  <CalibrationChart task={task} />
                </Panel>
              ) : (
                <Panel title="Residual checks" note="Mean, spread and Ljung–Box autocorrelation test of out-of-sample errors (origin-month averages).">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-xs text-ink-3">
                        <th className="py-2 font-medium">Model</th>
                        <th className="py-2 text-right font-medium">Mean</th>
                        <th className="py-2 text-right font-medium">SD</th>
                        <th className="py-2 text-right font-medium">Ljung–Box p</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries((task.residual_diagnostics ?? {}) as Record<string, Row>).map(([m, d]) => (
                        <tr key={m} className="border-b border-line/60 last:border-0">
                          <td className="py-1.5 text-ink">{modelLabel(m)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-2">{fmt(d.mean, 2)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-2">{fmt(d.sd, 2)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-2">{pValue(d.ljung_box_p)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Panel>
              )}
              <Panel title={`What ${modelLabel(impModel)} relied on`} note="Permutation importance on the final test fold: how much loss rises when a feature is shuffled. Blue: weather features. Importance is predictive reliance, not causal effect.">
                {imp[impModel]?.length ? <ImportanceChart items={imp[impModel]} /> : <Empty>No importance estimates for this task.</Empty>}
              </Panel>
            </div>
          )}

          {r.sensitivity.length > 0 && (
            <Panel title="Does the spike result depend on the threshold?" note="The spike definition was fixed before testing; these rows repeat the weather comparison at other thresholds.">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-xs text-ink-3">
                      <th className="py-2 font-medium">Horizon</th>
                      <th className="py-2 font-medium">Rise of at least</th>
                      <th className="py-2 text-right font-medium">Event rate</th>
                      <th className="py-2 text-right font-medium">Loss ratio B/A</th>
                      <th className="py-2 text-right font-medium">p (B better)</th>
                      <th className="py-2 text-right font-medium">Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(r.sensitivity as Row[]).map((s, i) => (
                      <tr key={i} className="border-b border-line/60 last:border-0">
                        <td className="py-1.5 text-ink-2">{String(s.horizon)}m</td>
                        <td className="py-1.5 text-ink-2">{pct(s.threshold)}{s.threshold === r.config.spike_threshold ? " (pre-specified)" : ""}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-2">{pct(s.event_rate, 1)}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-2">{fmt(s.relative_loss_b_vs_a)}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-2">{pValue(s.dm_p_b_better)}</td>
                        <td className="py-1.5 text-right"><VerdictBadge verdict={(s.verdict as string) ?? (s.status as string)} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Rolling-origin folds" note={`Models are refitted every ${String(r.config.refit_every)} months on all data whose target was observed by the refit date.`}>
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="border-b border-line text-left text-xs text-ink-3">
                      <th className="py-2 font-medium">Refit</th>
                      <th className="py-2 text-right font-medium">Train rows</th>
                      <th className="py-2 text-right font-medium">Test origins</th>
                      <th className="py-2 text-right font-medium">Test rows</th>
                    </tr>
                  </thead>
                  <tbody>
                    {((task?.folds ?? []) as Row[]).map((f) => (
                      <tr key={String(f.fold)} className="border-b border-line/60 last:border-0">
                        <td className="py-1.5 text-ink-2">{month(f.refit_date as string)}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-2">{String(f.train_rows)}</td>
                        <td className="py-1.5 text-right text-ink-2">{month(f.test_first_origin as string)}–{month(f.test_last_origin as string)}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-2">{String(f.test_rows)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
            <Panel title="Limitations of this experiment">
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
                {r.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
                {r.warnings.map((w, i) => (
                  <li key={`w${i}`} className="text-warn">{w}</li>
                ))}
              </ul>
            </Panel>
          </div>

          <Panel title="Reproduce this experiment" note="The manifest pins data snapshots, software versions, configuration and random seed.">
            <pre className="code-block">{`market-almanac reproduce ${r.experiment_id}`}</pre>
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-ink-2">Manifest</summary>
              <pre className="code-block mt-2 max-h-80 overflow-auto">{JSON.stringify(r.manifest, null, 2)}</pre>
            </details>
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-ink-2">Configuration</summary>
              <pre className="code-block mt-2 max-h-80 overflow-auto">{JSON.stringify(r.config, null, 2)}</pre>
            </details>
          </Panel>
        </div>
      )}
    </div>
  );
}
