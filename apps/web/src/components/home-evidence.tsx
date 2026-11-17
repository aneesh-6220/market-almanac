"use client";

import Link from "next/link";

import { ForestPlot } from "@/components/forest-plot";
import { Empty, ErrorState, Loading, VerdictBadge } from "@/components/ui";
import type { Comparison } from "@/lib/api";
import { month, VERDICT } from "@/lib/format";
import { useExperiment, useExperiments, useSources } from "@/lib/queries";

export function HomeEvidence() {
  const exps = useExperiments();
  const first = exps.data?.[0]?.id;
  const detail = useExperiment(first);
  if (exps.isLoading) return <Loading label="Loading latest experiment" />;
  if (exps.isError) return <ErrorState error={exps.error} what="experiments" />;
  if (!exps.data?.length)
    return (
      <Empty>
        No experiments have been run yet. Seed the demo with <code className="code">make demo</code> or run{" "}
        <code className="code">market-almanac backtest</code> on live data.
      </Empty>
    );
  const r = detail.data?.results;
  const primary = (r?.tasks ?? []).flatMap((t) => t.comparisons).filter((c): c is Comparison => !!c && c.role === "primary");
  const verdict = r?.conclusion?.verdict as string | undefined;
  return (
    <div className="rounded-md border border-line bg-surface p-5 md:p-7" data-testid="home-evidence">
      <div className="flex flex-wrap items-center gap-2 text-sm text-ink-3">
        <span>Latest experiment</span>
        {r?.synthetic && <span className="synthetic-band rounded px-1.5 text-ink">synthetic</span>}
      </div>
      <h2 className="mt-1 font-serif text-2xl text-ink">{exps.data[0].name}</h2>
      {detail.isLoading && <Loading />}
      {detail.isError && <ErrorState error={detail.error} what="experiment results" />}
      {r && (
        <>
          <p className="mt-4 font-serif text-xl leading-snug text-ink md:text-2xl">
            {VERDICT[verdict ?? ""]?.label ?? "No verdict"}.
          </p>
          <p className="mt-1 text-sm text-ink-2">{r.conclusion?.statement as string}</p>
          <div className="mt-6">{primary.length ? <ForestPlot rows={primary} compact /> : <Empty>No primary comparison could be evaluated.</Empty>}</div>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-sm">
            <span className="text-ink-3">
              Origins {month(r.data?.first_origin as string)} – {month(r.data?.last_origin as string)} · {r.data?.n_series as number} series
            </span>
            <Link href={`/lab?experiment=${r.experiment_id}`} className="font-medium text-rain underline-offset-4 hover:underline">
              Inspect the full evidence in the Model lab
            </Link>
          </div>
        </>
      )}
      {exps.data.length > 1 && (
        <ul className="mt-5 space-y-1.5 border-t border-line pt-4 text-sm">
          {exps.data.slice(1, 5).map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3">
              <Link href={`/lab?experiment=${e.id}`} className="truncate text-ink-2 hover:text-ink">
                {e.name}
              </Link>
              <VerdictBadge verdict={e.verdict} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SourceList() {
  const { data, isError, error } = useSources();
  if (isError) return <ErrorState error={error} what="data sources" />;
  const role: Record<string, string> = {
    hdx_hapi: "Monthly market prices: the series being forecast",
    nasa_power: "Daily rainfall and temperature near each market",
    world_bank: "Annual development context (population, GDP, inflation)",
    imf: "Monthly CPI and exchange rates for macro controls",
    faostat: "Annual national crop production, yield and area",
  };
  return (
    <dl className="divide-y divide-line border-y border-line">
      {(data ?? []).map((s) => (
        <div key={s.provider_id} className="grid gap-1 py-3 md:grid-cols-[14rem_1fr_auto] md:items-baseline md:gap-6">
          <dt className="font-medium text-ink">{s.name}</dt>
          <dd className="text-ink-2">{role[s.provider_id]}</dd>
          <dd className="text-xs text-ink-3">{s.verification === "live_verified" ? "live-verified" : "fixtures only"}</dd>
        </div>
      ))}
    </dl>
  );
}
