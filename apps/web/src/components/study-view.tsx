"use client";

import {
  Empty,
  ErrorState,
  Loading,
  Note,
  Panel,
  Stat,
  Tag,
} from "@/components/ui";
import { download, fmt, month, pct, pValue, toCsv } from "@/lib/format";

const fixed = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(3) : "—";
import { type Study, useStudy } from "@/lib/research-api";

type Row = Record<string, unknown>;
const EVIDENCE: Record<
  string,
  { label: string; tone: "good" | "warn" | "muted" | "neutral" }
> = {
  improvement: { label: "Improvement established", tone: "good" },
  improvement_fragile: { label: "Improvement, fragile", tone: "warn" },
  deterioration: { label: "Forecasts worse", tone: "warn" },
  not_established: { label: "No improvement established", tone: "neutral" },
  insufficient_data: { label: "Insufficient data", tone: "muted" },
};
const REPO = "https://github.com/aneesh-6220/market-almanac";

/** Ratio with interval on a log scale; 1.0 (no difference) is the reference line. */
function RatioBar({
  ratio,
  lo,
  hi,
}: {
  ratio?: number | null;
  lo?: number | null;
  hi?: number | null;
}) {
  const min = 0.8;
  const max = 1.25;
  const x = (v: number) =>
    ((Math.log(Math.min(Math.max(v, min), max)) - Math.log(min)) /
      (Math.log(max) - Math.log(min))) *
    100;
  return (
    <div className="relative h-6 min-w-[9rem]" aria-hidden>
      <div
        className="absolute inset-y-0 w-px bg-ink-3"
        style={{ left: `${x(1)}%` }}
      />
      {typeof lo === "number" && typeof hi === "number" && (
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-rain/40"
          style={{
            left: `${x(lo)}%`,
            width: `${Math.max(x(hi) - x(lo), 0.6)}%`,
          }}
        />
      )}
      {typeof ratio === "number" && (
        <div
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-rain"
          style={{ left: `${x(ratio)}%` }}
        />
      )}
    </div>
  );
}

function Table({
  cols,
  rows,
  caption,
}: {
  cols: [string, string, ((r: Row) => React.ReactNode)?][];
  rows: Row[];
  caption: string;
}) {
  if (!rows.length) return <Empty>Nothing to show.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-left text-xs text-ink-3">
          <tr className="border-b border-line">
            {cols.map(([k, label]) => (
              <th key={k} scope="col" className="py-2 pr-3">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60">
              {cols.map(([k, , render]) => (
                <td key={k} className="py-1.5 pr-3 tabular-nums">
                  {render ? render(r) : fmt(r[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Predictive({ s }: { s: Study }) {
  const res = s.results as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  const hyps: Row[] = res.hypotheses ?? [];
  return (
    <>
      <Panel
        title="Pre-declared hypotheses"
        note={`Loss ratio = challenger / baseline mean squared error, country-balanced. Below 1 favours the challenger. p-values ${res.multiplicity?.method === "holm" ? "Holm" : res.multiplicity?.method === "benjamini_hochberg" ? "Benjamini–Hochberg" : res.multiplicity?.method}-adjusted across ${(res.multiplicity?.family ?? []).join(", ")}.`}
      >
        <div className="space-y-4">
          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {hyps.map((h: any) => {
            const r = h.result ?? {};
            const ci = r.ci_primary ?? {};
            const ev = EVIDENCE[h.evidence?.class] ?? {
              label: h.evidence?.class,
              tone: "muted" as const,
            };
            return (
              <article
                key={h.hypothesis.id}
                className="rounded border border-line p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-medium text-ink">
                      {h.hypothesis.id}: {h.hypothesis.statement}
                    </div>
                    <div className="text-xs text-ink-3">
                      family {h.hypothesis.challenger} vs{" "}
                      {h.hypothesis.baseline} · horizon {h.hypothesis.horizon}{" "}
                      month{h.hypothesis.horizon > 1 ? "s" : ""}
                    </div>
                  </div>
                  <Tag tone={ev.tone}>{ev.label}</Tag>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  <Stat
                    label="Loss ratio"
                    value={fmt(r.loss_ratio, 4)}
                    hint={
                      r.pct_change_in_loss != null
                        ? `${r.pct_change_in_loss > 0 ? "+" : ""}${r.pct_change_in_loss.toFixed(1)}% loss`
                        : undefined
                    }
                  />
                  <Stat
                    label="95% interval"
                    value={`${fixed(ci.ci_low)} – ${fixed(ci.ci_high)}`}
                    hint="countries × month blocks"
                  />
                  <Stat
                    label="p (adjusted)"
                    value={pValue(h.p_adjusted)}
                    hint={`raw ${pValue(h.p_raw)}`}
                  />
                  <Stat
                    label="Evaluation months"
                    value={fmt(r.n_months)}
                    hint={
                      r.first_origin
                        ? `${month(r.first_origin)} – ${month(r.last_origin)}`
                        : undefined
                    }
                  />
                  <Stat
                    label="Countries"
                    value={fmt(r.n_countries)}
                    hint={`${fmt(r.n_series)} series`}
                  />
                  <Stat
                    label="Matched forecasts"
                    value={fmt(r.n_forecasts)}
                    hint="not independent observations"
                  />
                </div>
                <div className="mt-3 max-w-md">
                  <RatioBar
                    ratio={r.loss_ratio}
                    lo={ci.ci_low}
                    hi={ci.ci_high}
                  />
                  <div className="flex justify-between text-[11px] text-ink-3">
                    <span>0.8 (challenger better)</span>
                    <span>1.0</span>
                    <span>1.25 (worse)</span>
                  </div>
                </div>
                <p className="mt-2 text-sm text-ink-2">{h.evidence?.text}</p>
                {r.sign_test_countries && (
                  <p className="mt-1 text-xs text-ink-3">
                    Countries where the challenger had lower loss:{" "}
                    {r.sign_test_countries.better} of{" "}
                    {r.sign_test_countries.better + r.sign_test_countries.worse}{" "}
                    (sign test p ={" "}
                    {pValue(r.sign_test_countries.p_one_sided_better)}). Three
                    most influential months carry{" "}
                    {pct(r.influence?.top_share_of_total_difference)} of the
                    loss difference; ratio without them{" "}
                    {fmt(r.influence?.ratio_without_top, 4)}.
                    Leave-one-country-out range{" "}
                    {fmt(r.leave_one_country_out?.min, 4)}–
                    {fmt(r.leave_one_country_out?.max, 4)}.
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel
          title="Is price history itself skilful?"
          note="Ridge A against simple benchmarks on the same forecasts. Below 1: the model beats the benchmark."
        >
          <Table
            caption="Baseline skill"
            rows={res.baseline_skill ?? []}
            cols={[
              [
                "baseline",
                "Benchmark",
                (r) => String(r.baseline).replace("_", "-"),
              ],
              ["horizon", "h"],
              ["loss_ratio", "Loss ratio", (r) => fmt(r.loss_ratio, 4)],
              [
                "p_challenger_better",
                "p (A better)",
                (r) => pValue(r.p_challenger_better),
              ],
              ["n_countries", "Countries"],
            ]}
          />
        </Panel>
        <Panel
          title="Robustness and negative controls"
          note="The same contrasts re-estimated. A negative control should not show the primary gain."
        >
          <Table
            caption="Robustness and negative controls"
            rows={res.variants ?? []}
            cols={[
              [
                "variant",
                "Variant",
                (r) => String(r.variant).replaceAll("_", " "),
              ],
              [
                "kind",
                "Kind",
                (r) => (
                  <Tag tone={r.kind === "negative_control" ? "warn" : "muted"}>
                    {String(r.kind).replace("_", " ")}
                  </Tag>
                ),
              ],
              ["horizon", "h"],
              ["loss_ratio", "Loss ratio", (r) => fmt(r.loss_ratio, 4)],
              [
                "p_challenger_better",
                "p (B better)",
                (r) => pValue(r.p_challenger_better),
              ],
            ]}
          />
        </Panel>
      </div>

      <Panel
        title="Heterogeneity (exploratory)"
        note="Subgroup ratios with Benjamini–Hochberg q-values. Not part of the confirmatory family; small subgroups have wide uncertainty."
      >
        <Table
          caption="Heterogeneity"
          rows={res.heterogeneity ?? []}
          cols={[
            ["hypothesis", "Hyp."],
            [
              "dimension",
              "Dimension",
              (r) => String(r.dimension).replaceAll("_", " "),
            ],
            ["level", "Level", (r) => String(r.level)],
            ["loss_ratio", "Loss ratio", (r) => fmt(r.loss_ratio, 4)],
            ["q_value_bh", "q (BH)", (r) => pValue(r.q_value_bh)],
            ["n_countries", "Countries"],
            ["n_series", "Series"],
          ]}
        />
      </Panel>

      <Panel
        title="By country (descriptive, alphabetical)"
        note="Per-country loss ratios are shown for transparency and are deliberately not ranked: with about 50 evaluation months each, many differences are noise, and no per-country test is part of the confirmatory family."
        actions={
          <button
            type="button"
            className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface-2"
            onClick={() =>
              download(`${s.id}_countries.csv`, toCsv(res.countries ?? []))
            }
          >
            Download CSV
          </button>
        }
      >
        <Table
          caption="Per-country ratios"
          rows={[...(res.countries ?? [])].sort(
            (a: Row, b: Row) =>
              String(a.country_iso3).localeCompare(String(b.country_iso3)) ||
              Number(a.horizon) - Number(b.horizon),
          )}
          cols={[
            ["country_iso3", "Country", (r) => String(r.country_iso3)],
            ["macro_region", "Region", (r) => String(r.macro_region)],
            ["horizon", "h"],
            ["ratio_B_vs_A", "B / A", (r) => fmt(r.ratio_B_vs_A, 3)],
            [
              "ratio_A_vs_naive",
              "A / no-change",
              (r) => fmt(r.ratio_A_vs_naive, 3),
            ],
            ["n_series", "Series"],
            ["n_months", "Months"],
          ]}
        />
      </Panel>

      <Panel
        title="Population"
        note={`${res.n_groups} commodity groups in ${res.n_countries} countries, selected from metadata before any model was estimated.`}
      >
        <Table
          caption="Analysis groups"
          rows={res.groups ?? []}
          cols={[
            ["country_iso3", "Country", (r) => String(r.country_iso3)],
            ["commodity_name", "Commodity", (r) => String(r.commodity_name)],
            ["unit", "Unit", (r) => String(r.unit)],
            ["currency", "Currency", (r) => String(r.currency)],
            ["eligible_series", "Eligible series"],
          ]}
        />
      </Panel>
    </>
  );
}

function Descriptive({ s }: { s: Study }) {
  const groups: Row[] =
    (s.results as Record<string, any>).descriptive?.groups ?? []; // eslint-disable-line @typescript-eslint/no-explicit-any
  return (
    <Panel
      title="Group summaries"
      note="Nominal local-currency prices. Trends include inflation and depreciation, so they are not comparable across countries."
      actions={
        <button
          type="button"
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface-2"
          onClick={() => download(`${s.id}.csv`, toCsv(groups))}
        >
          Download CSV
        </button>
      }
    >
      <Table
        caption="Descriptive statistics by commodity group"
        rows={groups}
        cols={[
          ["country_iso3", "Country", (r) => String(r.country_iso3)],
          ["commodity_name", "Commodity", (r) => String(r.commodity_name)],
          ["unit", "Unit", (r) => String(r.unit)],
          ["series", "Series"],
          [
            "median_trend_pct_per_year",
            "Trend %/yr",
            (r) => fmt(r.median_trend_pct_per_year, 3),
          ],
          [
            "median_volatility_sd_dlog",
            "Volatility",
            (r) => fmt(r.median_volatility_sd_dlog, 3),
          ],
          [
            "median_seasonal_amplitude_log",
            "Seasonal amplitude",
            (r) => fmt(r.median_seasonal_amplitude_log, 3),
          ],
          ["modal_seasonal_peak_month", "Peak month"],
          [
            "mean_pairwise_correlation_dlog",
            "Co-movement",
            (r) => fmt(r.mean_pairwise_correlation_dlog, 2),
          ],
        ]}
      />
    </Panel>
  );
}

export function StudyView({ id }: { id: string }) {
  const q = useStudy(id);
  if (q.isLoading) return <Loading label="Loading study" />;
  if (q.error) return <ErrorState error={q.error} what={`study ${id}`} />;
  const s = q.data!;
  const res = s.results as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  const commit = s.freeze?.code?.git_commit as string | undefined;
  return (
    <div className="space-y-6">
      <section className="rounded-md border border-line bg-surface p-5">
        <div className="flex flex-wrap gap-2">
          <Tag tone={s.evidence_class === "confirmatory" ? "good" : "muted"}>
            {s.evidence_class}
          </Tag>
          <Tag>{s.study_type}</Tag>
          {s.frozen && <Tag tone="good">frozen before estimation</Tag>}
        </div>
        <h2 className="mt-3 font-serif text-2xl text-ink">{s.title}</h2>
        <p className="mt-2 text-ink-2">{s.headline}</p>
        <dl className="mt-4 grid gap-x-4 gap-y-2 text-sm md:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-ink-3">Question</dt>
          <dd>{s.question}</dd>
          <dt className="text-ink-3">Hypothesis</dt>
          <dd>{s.hypothesis}</dd>
          <dt className="text-ink-3">Estimand</dt>
          <dd>{s.estimand}</dd>
          {s.families && (
            <>
              <dt className="text-ink-3">Model families</dt>
              <dd>
                {Object.entries(s.families).map(([k, v]) => (
                  <div key={k}>
                    <span className="font-medium">{k}</span>: {v}
                  </div>
                ))}
              </dd>
            </>
          )}
          <dt className="text-ink-3">Specification</dt>
          <dd className="break-all font-mono text-xs">sha256 {s.spec_hash}</dd>
          {s.frozen && (
            <>
              <dt className="text-ink-3">Frozen</dt>
              <dd>
                {String(s.freeze?.frozen_at ?? "")
                  .slice(0, 19)
                  .replace("T", " ")}{" "}
                UTC from commit{" "}
                {commit ? (
                  <a
                    className="font-mono text-xs text-rain underline-offset-4 hover:underline"
                    href={`${REPO}/commit/${commit}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {commit.slice(0, 10)}
                  </a>
                ) : (
                  "—"
                )}
                ; selection hash{" "}
                <span className="font-mono text-xs">
                  {String(s.freeze?.selection_hash ?? "").slice(0, 16)}
                </span>
              </dd>
            </>
          )}
          <dt className="text-ink-3">Inputs</dt>
          <dd>
            {Object.keys(res.data_snapshots ?? {}).length} hashed data snapshots
            (see the downloadable record)
          </dd>
        </dl>
        <div className="mt-4 flex flex-wrap gap-3 text-sm">
          <button
            type="button"
            className="rounded border border-line px-3 py-1.5 hover:bg-surface-2"
            onClick={() =>
              download(
                `${s.id}.json`,
                JSON.stringify(s, null, 1),
                "application/json",
              )
            }
          >
            Download full results (JSON)
          </button>
          <a
            className="rounded border border-line px-3 py-1.5 hover:bg-surface-2"
            href={`${REPO}/tree/main/docs/research`}
            target="_blank"
            rel="noreferrer"
          >
            Protocol and specification
          </a>
        </div>
      </section>
      {s.study_type === "predictive" && <Predictive s={s} />}
      {s.study_type === "descriptive" && <Descriptive s={s} />}
      <Panel title="Limitations">
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          {(res.limitations ?? []).map((l: string) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Panel>
      <Panel title="Reproduce">
        <pre className="overflow-x-auto rounded bg-surface-2 p-3 text-xs">
          {[
            `git checkout ${s.frozen ? "protocol-atlas-v1  # the frozen protocol tag" : "main"}`,
            `uv run market-almanac global ingest --countries <ISO3,...>      # or install the data bundle`,
            `uv run market-almanac research run docs/research/specs/${s.id}.yaml`,
            `uv run market-almanac research verify data/studies/live/${s.id}`,
            ...(s.study_type === "predictive"
              ? [
                  `uv run python scripts/audit/recompute_atlas.py data/studies/live/${s.id}`,
                ]
              : []),
          ].join("\n")}
        </pre>
        <Note>
          {s.study_type === "predictive"
            ? "Predictive, not causal. Backtests use today's revised data with an assumed publication lag; they are not real-time forecasts."
            : "Descriptive summaries test no hypothesis and support no causal claim."}
        </Note>
      </Panel>
    </div>
  );
}
