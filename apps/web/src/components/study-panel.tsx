"use client";

import Link from "next/link";
import { useState } from "react";

import { Empty, Loading, Note, Panel, Tag } from "@/components/ui";
import { pValue } from "@/lib/format";
import { useStudy, type StudyRow } from "@/lib/market-api";

export const STUDY_ID = "sahel-production-weather-v1";
const COUNTRY: Record<string, string> = { BFA: "Burkina Faso", MLI: "Mali", NER: "Niger" };
const CONTRAST: Record<string, string> = {
  P_vs_A: "Production-region weather vs price history",
  P_vs_B: "Production-region vs market-local weather",
  B_vs_A: "Market-local weather vs price history",
  P_vs_placebo_shift: "Real vs time-shifted production features",
  P_vs_placebo_crop: "Own-crop vs wrong-crop production features",
};
const OUTCOME: Record<string, { text: string; tone: "good" | "neutral" | "warn" }> = {
  positive: { text: "Improvement established", tone: "good" },
  inconclusive: { text: "Inconclusive", tone: "warn" },
  no_established_improvement: { text: "No established improvement", tone: "neutral" },
};

const f3 = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(3));

function Rows({ rows, holm }: { rows: StudyRow[]; holm: boolean }) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Study comparison table">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th className="py-2 pr-3 font-medium">Country</th>
            <th className="py-2 pr-3 font-medium">Comparison</th>
            <th className="py-2 pr-3 text-right font-medium">Horizon</th>
            <th className="py-2 pr-3 text-right font-medium">Months</th>
            <th className="py-2 pr-3 text-right font-medium">Forecasts</th>
            <th className="py-2 pr-3 text-right font-medium">Loss ratio</th>
            <th className="py-2 pr-3 text-right font-medium">95% interval</th>
            <th className="py-2 pr-3 text-right font-medium">p (one-sided)</th>
            {holm && <th className="py-2 pr-3 text-right font-medium">p (Holm)</th>}
            <th className="py-2 font-medium">Depends on few months?</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60">
              <td className="py-2 pr-3 text-ink">{COUNTRY[r.country] ?? r.country}</td>
              <td className="py-2 pr-3 text-ink-2">{CONTRAST[r.contrast] ?? r.contrast}</td>
              <td className="py-2 pr-3 text-right text-ink-2">{r.horizon} mo</td>
              <td className="py-2 pr-3 text-right text-ink-2">{r.n_months}</td>
              <td className="py-2 pr-3 text-right text-ink-2">{r.n_rows.toLocaleString()}</td>
              <td className="py-2 pr-3 text-right font-medium text-ink">{f3(r.loss_ratio)}</td>
              <td className="py-2 pr-3 text-right text-ink-2">
                {f3(r.ci_low)} – {f3(r.ci_high)}
              </td>
              <td className="py-2 pr-3 text-right text-ink-2">{pValue(r.p_b_better)}</td>
              {holm && <td className="py-2 pr-3 text-right text-ink-2">{pValue(r.p_holm)}</td>}
              <td className="py-2 text-ink-2">{r.fragile ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The pre-specified production-region study: outcome, confirmatory table, falsification and sensitivity checks. */
export function StudyPanel({ compact = false }: { compact?: boolean }) {
  const [phase, setPhase] = useState<"confirmatory" | "exploratory">("confirmatory");
  const study = useStudy(STUDY_ID, phase);
  const [tab, setTab] = useState<"primary" | "placebo" | "sensitivity">("primary");
  if (study.isLoading) return <Loading label="Loading study" />;
  if (study.isError || !study.data) {
    return compact ? (
      <Empty>
        The pre-registered study runs on live data, which this deployment has not loaded. Its published outcome for Mali and Niger: no established improvement from
        production-region weather (0 of 8 confirmatory tests significant after Holm adjustment). The full tables are in{" "}
        <code className="code">docs/research/generated/sahel_study_confirmatory.md</code>; install the public data bundle to see them here.
      </Empty>
    ) : <Empty>No stored results for the production-region study in this deployment. Run <code className="code">market-almanac study</code> on live data.</Empty>;
  }
  const d = study.data;
  const evidence = phase;
  const pooled = d.pooled.filter((r) => r.evidence_class === evidence);
  const primary = pooled.filter((r) => r.variant === "primary" && (phase === "exploratory" || r.contrast !== "B_vs_A" || !compact));
  const placebo = pooled.filter((r) => r.variant.startsWith("placebo"));
  const sens = pooled.filter((r) => ["lag0", "lag2", "rawprecip"].includes(r.variant) && r.contrast !== "B_vs_A");
  const out = OUTCOME[d.confirmatory.outcome.label] ?? { text: d.confirmatory.outcome.label, tone: "neutral" as const };
  const nSeries = d.experiments.filter((e) => e.variant === "primary" && e.evidence_class === evidence).reduce((a, e) => a + e.n_series, 0);

  if (compact) {
    return (
      <div className="rounded-md border border-line bg-surface p-5 md:p-7" data-testid="study-summary">
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-3">
          <span>Pre-registered study · Mali and Niger</span>
          <Tag tone={out.tone}>{out.text}</Tag>
        </div>
        <h2 className="mt-2 font-serif text-2xl leading-snug text-ink">Does rainfall where crops are grown help forecast staple prices?</h2>
        <p className="mt-3 text-ink-2">{d.confirmatory.outcome.statement}</p>
        <div className="mt-4">
          <Rows rows={primary.filter((r) => r.contrast === "P_vs_A")} holm />
        </div>
        <p className="mt-3 text-xs text-ink-3">
          Loss ratio above 1 means the weather-augmented model had larger out-of-sample squared error. {nSeries} price series; test origins from 2021.
        </p>
        <Link href="/lab" className="mt-3 inline-block text-sm font-medium text-rain underline-offset-4 hover:underline">
          Read the full evidence in the Research Lab
        </Link>
      </div>
    );
  }

  return (
    <Panel
      title="Production-region weather study"
      note="Does weather over crop-growing areas, aligned with the growing season, improve price forecasts beyond price history and market-local weather?"
      actions={
        <div className="flex gap-1" role="tablist" aria-label="Evidence class">
          {(["confirmatory", "exploratory"] as const).map((ph) => (
            <button
              key={ph}
              type="button"
              role="tab"
              aria-selected={phase === ph}
              onClick={() => setPhase(ph)}
              className={`rounded px-3 py-1.5 text-sm ${phase === ph ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {ph === "confirmatory" ? "Confirmatory (Mali, Niger)" : "Exploratory (Burkina Faso)"}
            </button>
          ))}
        </div>
      }
    >
      {phase === "confirmatory" ? (
        <div className="mb-4 flex flex-wrap items-start gap-3">
          <Tag tone={out.tone}>{out.text}</Tag>
          <p className="max-w-3xl text-sm text-ink-2">{d.confirmatory.outcome.statement}</p>
        </div>
      ) : (
        <div className="mb-4">
          <Note tone="warn">
            Exploratory evidence. Burkina Faso&rsquo;s test period was examined while the method was developed, so these results cannot confirm a hypothesis. They are shown for
            transparency.
          </Note>
        </div>
      )}
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Study tables">
        {(
          [
            ["primary", "Main comparisons"],
            ["placebo", "Falsification checks"],
            ["sensitivity", "Sensitivity analyses"],
          ] as const
        ).map(([k, name]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`rounded px-3 py-1.5 text-sm ${tab === k ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"}`}>
            {name}
          </button>
        ))}
      </div>
      {tab === "primary" && <Rows rows={primary} holm={phase === "confirmatory"} />}
      {tab === "placebo" && (placebo.length ? <Rows rows={placebo} holm={false} /> : <Empty>No falsification runs stored for this phase.</Empty>)}
      {tab === "sensitivity" &&
        (sens.length ? (
          <>
            <p className="mb-2 text-sm text-ink-3">Price lag 0 and 2 change which price is assumed published at the forecast origin; raw precipitation switches off quality control.</p>
            <Rows rows={sens.map((r) => ({ ...r, contrast: `${r.contrast}` , country: `${COUNTRY[r.country] ?? r.country} · ${r.variant === "rawprecip" ? "raw rainfall" : `price lag ${r.variant.slice(3)}`}` }))} holm={false} />
          </>
        ) : (
          <Empty>No sensitivity runs stored for this phase.</Empty>
        ))}
      <p className="mt-4 text-xs leading-relaxed text-ink-3">
        Loss ratio = mean squared error of the second model divided by that of the first, pooled over the country&rsquo;s crops; below 1 favours the second model. Interval: moving-block
        bootstrap over months. p: one-sided Diebold–Mariano test on monthly mean loss differences{phase === "confirmatory" ? `, Holm-adjusted across the ${d.confirmatory.n_tests} pre-specified tests` : ""}. Primary timing
        assumes prices are published with a {d.spec.primary_lag}-month lag. A non-significant result means no established improvement, not evidence of no effect. Protocol:{" "}
        <code className="code">docs/research/RESEARCH_PROTOCOL.md</code>.
      </p>
    </Panel>
  );
}
