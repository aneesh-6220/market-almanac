"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Empty, ErrorState, Field, Loading, Note, PageHeader, Panel, Select, Stat, Tag } from "@/components/ui";
import type { Source } from "@/lib/api";
import { dateTime, download, month, pct, toCsv } from "@/lib/format";
import { useCoverageSummary } from "@/lib/market-api";
import { useCountries, useJobs, useQuality, useSnapshots, useSources, useStatus } from "@/lib/queries";
import { useUrlState } from "@/lib/url-state";

const HEALTH_TONE: Record<string, "good" | "warn" | "muted" | "neutral"> = {
  healthy: "good",
  degraded: "warn",
  unavailable: "warn",
  not_configured: "muted",
  unknown: "muted",
};

function SourceCard({ s }: { s: Source }) {
  return (
    <article className="rounded-md border border-line bg-surface p-5" aria-label={s.name}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-base font-semibold text-ink">{s.name}</h3>
        <div className="flex flex-wrap gap-1.5">
          <Tag tone={HEALTH_TONE[s.health_status] ?? "muted"}>{s.health_status.replace("_", " ")}</Tag>
          <Tag tone={s.verification === "live_verified" ? "good" : "muted"}>{s.verification === "live_verified" ? "live-verified" : "fixtures only"}</Tag>
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-2">{s.description}</p>
      <dl className="mt-4 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-ink-3">Licence</dt>
        <dd className="text-ink-2">{s.license}</dd>
        <dt className="text-ink-3">Attribution</dt>
        <dd className="text-ink-2">{s.attribution}</dd>
        <dt className="text-ink-3">Access</dt>
        <dd className="text-ink-2">{s.auth_kind === "none" ? "Open, no key" : `${s.auth_kind.replace("_", " ")} · ${s.configured ? "configured" : "not configured"}`}</dd>
        <dt className="text-ink-3">Last health check</dt>
        <dd className="text-ink-2">
          {dateTime(s.health_checked_at)}
          {s.health_latency_ms != null && ` · ${Math.round(s.health_latency_ms)} ms`}
        </dd>
        <dt className="text-ink-3">Last live success</dt>
        <dd className="text-ink-2">{dateTime(s.last_live_success_at)}</dd>
        <dt className="text-ink-3">Last retrieval</dt>
        <dd className="text-ink-2">{dateTime(s.last_retrieval_at)}</dd>
      </dl>
      {s.health_message && <p className="mt-3 text-xs text-ink-3">{s.health_message}</p>}
      {s.caveats.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
          {s.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex gap-4 text-sm">
        <a className="text-rain underline-offset-4 hover:underline" href={s.homepage} target="_blank" rel="noreferrer">
          Source site
        </a>
        <a className="text-rain underline-offset-4 hover:underline" href={s.docs_url} target="_blank" rel="noreferrer">
          API documentation
        </a>
      </div>
    </article>
  );
}

const FEATURES: [string, string][] = [
  ["price_history", "Price history"],
  ["comparison", "Comparison"],
  ["unusual_movements", "Unusual movements"],
  ["weather_context", "Weather context"],
  ["production_region_context", "Production-region context"],
  ["forecast_evaluation", "Forecast evaluation"],
];

function CoverageTable() {
  const cov = useCoverageSummary();
  if (cov.isLoading) return <Loading label="Loading coverage" />;
  if (cov.isError) return <ErrorState error={cov.error} what="the coverage inventory" />;
  const d = cov.data;
  if (!d || d.countries.length === 0) return <Empty>No price data have been ingested yet.</Empty>;
  return (
    <section aria-label="Coverage by country">
      <h2 className="mb-1 font-serif text-2xl text-ink">Coverage by country</h2>
      <p className="mb-4 max-w-3xl text-sm text-ink-2">
        {d.scope_note} Price history and forecast evaluation are different things: most series can be explored and compared, far fewer are complete enough to evaluate a forecasting
        model, and fewer still are covered by one.
      </p>
      <div className="overflow-x-auto rounded-md border border-line bg-surface" tabIndex={0} role="region" aria-label="Coverage table">
        <table className="w-full min-w-[980px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th className="px-3 py-2 font-medium">Country</th>
              <th className="px-3 py-2 text-right font-medium">Markets</th>
              <th className="px-3 py-2 text-right font-medium">Commodities</th>
              <th className="px-3 py-2 text-right font-medium">Series (1+ year)</th>
              <th className="px-3 py-2 text-right font-medium">Complete enough to evaluate</th>
              <th className="px-3 py-2 text-right font-medium">Covered by an evaluation</th>
              <th className="px-3 py-2 font-medium">Period</th>
              <th className="px-3 py-2 text-right font-medium">Updated in last 3 months</th>
              <th className="px-3 py-2 font-medium">Supported</th>
            </tr>
          </thead>
          <tbody>
            {d.countries.map((c) => (
              <tr key={c.country_iso3} className="border-b border-line/60 align-top">
                <td className="px-3 py-2">
                  <Link href={`/explorer?country=${c.country_iso3}`} className="font-medium text-ink underline decoration-line underline-offset-2">
                    {c.name}
                  </Link>
                  <div className="text-xs text-ink-3">{c.currencies.join(", ")}</div>
                </td>
                <td className="px-3 py-2 text-right text-ink-2">{c.markets}</td>
                <td className="px-3 py-2 text-right text-ink-2">{c.commodities}</td>
                <td className="px-3 py-2 text-right text-ink-2">
                  {c.usable_series.toLocaleString()} <span className="text-xs text-ink-3">of {c.series.toLocaleString()}</span>
                </td>
                <td className="px-3 py-2 text-right text-ink-2">{c.eligible_series.toLocaleString()}</td>
                <td className="px-3 py-2 text-right text-ink-2">{c.forecast_evaluated_series.toLocaleString()}</td>
                <td className="whitespace-nowrap px-3 py-2 text-ink-2">
                  {month(c.first_period)} – {month(c.last_period)}
                </td>
                <td className="px-3 py-2 text-right text-ink-2">{c.series_updated_within_3_months.toLocaleString()}</td>
                <td className="px-3 py-2">
                  <div className="flex max-w-[22rem] flex-wrap gap-1">
                    {FEATURES.map(([k, name]) => (
                      <Tag key={k} tone={c.features[k] ? "good" : "muted"}>
                        {c.features[k] ? name : `no ${name.toLowerCase()}`}
                      </Tag>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.definitions && (
        <dl className="mt-3 grid gap-x-6 gap-y-1 text-xs text-ink-3 md:grid-cols-3">
          <div>
            <dt className="inline font-medium text-ink-2">Series (1+ year): </dt>
            <dd className="inline">{d.definitions.usable}.</dd>
          </div>
          <div>
            <dt className="inline font-medium text-ink-2">Complete enough to evaluate: </dt>
            <dd className="inline">{d.definitions.eligible}.</dd>
          </div>
          <div>
            <dt className="inline font-medium text-ink-2">Covered by an evaluation: </dt>
            <dd className="inline">{d.definitions.forecast_evaluated}.</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

export function DataClient() {
  const status = useStatus();
  const sources = useSources();
  const { get, set } = useUrlState();
  const country = get("country");
  const countries = useCountries();
  const [onlyEligible, setOnlyEligible] = useState(false);
  const quality = useQuality({ country: country || undefined, eligible_only: onlyEligible || undefined, limit: 1000 });
  const snapshots = useSnapshots();
  const jobs = useJobs();
  const q = quality.data;
  const series = useMemo(() => q?.series ?? [], [q]);
  const summary = (q?.summary ?? {}) as Record<string, unknown>;

  return (
    <div>
      <PageHeader
        title="Data coverage"
        lede="What this deployment holds, how complete and how recent it is, where every number comes from, and which series are fit for forecast evaluation."
      />

      {status.data?.synthetic && (
        <div className="mb-6">
          <Note tone="warn">Demo mode: the datasets below are synthetic and generated offline. Source health reflects the real providers, which demo mode never calls.</Note>
        </div>
      )}

      <CoverageTable />

      <h2 className="mb-3 mt-10 font-serif text-2xl text-ink">Sources</h2>
      {sources.isError && <ErrorState error={sources.error} what="sources" />}
      {sources.isLoading && <Loading />}
      <div className="mb-10 grid gap-4 lg:grid-cols-2">{sources.data?.map((s) => <SourceCard key={s.provider_id} s={s} />)}</div>

      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-serif text-2xl text-ink">Price-series quality</h2>
        <div className="w-64">
          <Field label="Country" htmlFor="dq-country">
            <Select
              id="dq-country"
              value={country}
              onChange={(v) => set({ country: v })}
              options={(countries.data ?? []).map((c) => ({ value: c.iso3, label: c.name }))}
              placeholder="All countries"
            />
          </Field>
        </div>
      </div>
      {quality.isError && <Empty>No quality report yet. Run <code className="code">market-almanac validate</code>.</Empty>}
      {quality.isLoading && <Loading />}
      {q && (
        <div className="mb-10 grid grid-cols-[minmax(0,1fr)] gap-5">
          <div className="grid grid-cols-2 gap-5 rounded-md border border-line bg-surface p-5 md:grid-cols-5">
            <Stat label="Price records" value={String(summary.price_records ?? "—")} hint="all countries in this report" />
            <Stat label="Series" value={String(summary.series ?? "—")} />
            <Stat label="Eligible to forecast" value={String(summary.eligible_series ?? "—")} />
            <Stat label="Flagged extreme moves" value={String(summary.extreme_changes ?? "—")} hint="kept, never deleted" />
            <Stat label="Report" value={<span className="text-sm">{dateTime(q.created_at)}</span>} />
          </div>

          {q.consistency_issues.length > 0 && (
            <Panel title="Consistency checks" note="Units, currencies and coordinates that do not line up. Incompatible records are kept as separate series, never merged.">
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
                {q.consistency_issues.slice(0, 30).map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
              {(q.consistency_issues_total ?? q.consistency_issues.length) > 30 && (
                <p className="mt-2 text-xs text-ink-3">and {(q.consistency_issues_total ?? q.consistency_issues.length) - 30} more</p>
              )}
            </Panel>
          )}

          <Panel
            title="Every series and why it is or is not eligible"
            note={`Eligible series need at least ${String((q.criteria as Record<string, unknown> | undefined)?.min_observations ?? 48)} monthly prices, 80% coverage, no gap longer than six months, market coordinates, and actual (not forecast) prices.`}
            actions={
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-ink-2">
                  <input type="checkbox" checked={onlyEligible} onChange={(e) => setOnlyEligible(e.target.checked)} className="h-4 w-4 accent-[var(--rain)]" />
                  Eligible only
                </label>
                <button
                  type="button"
                  className="h-8 rounded border border-line px-3 text-sm text-ink hover:bg-surface-2"
                  onClick={() =>
                    download(
                      "market_almanac_series_quality.csv",
                      toCsv(series.map((s) => ({ ...s, reasons: s.reasons.join("; "), extreme_change_classes: JSON.stringify(s.extreme_change_classes) }))),
                    )
                  }
                >
                  Download CSV
                </button>
              </div>
            }
          >
            {(q.series_total ?? 0) > series.length && (
              <p className="mb-2 text-sm text-ink-3">
                Showing the first {series.length.toLocaleString()} of {(q.series_total ?? 0).toLocaleString()} series. Choose a country to narrow the list.
              </p>
            )}
            <div className="max-h-[32rem] overflow-auto">
              <table className="w-full min-w-[52rem] text-sm">
                <caption className="sr-only">Series quality</caption>
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-left text-xs text-ink-3">
                    <th scope="col" className="py-2 pr-3 font-medium">Market</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Commodity</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Unit · type</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Span</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Months</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Coverage</th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">Gap</th>
                    <th scope="col" className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {series.map((s) => (
                    <tr key={s.series_id} className="border-b border-line/60 align-top last:border-0">
                      <td className="py-1.5 pr-3">
                        <Link className="text-ink hover:text-rain" href={`/market?series=${s.series_id}`}>
                          {s.market_name}
                        </Link>
                        <div className="text-xs text-ink-3">{s.country_iso3}</div>
                      </td>
                      <td className="py-1.5 pr-3 text-ink-2">{s.commodity_name}</td>
                      <td className="py-1.5 pr-3 text-ink-2">
                        {s.currency}/{s.unit} · {s.price_type}
                      </td>
                      <td className="py-1.5 pr-3 text-ink-2">
                        {month(s.first_period)}–{month(s.last_period)}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-2">{s.n_observations}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-2">{pct(s.coverage)}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-2">{s.longest_gap_months}</td>
                      <td className="py-1.5">
                        {s.eligible ? <Tag tone="good">Eligible</Tag> : <span className="text-xs text-warn">{s.reasons.join("; ")}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {q.extremes.length > 0 && (
            <Panel title="Flagged extreme moves" note="Monthly changes more than five robust standard deviations from typical. Corroborated shocks moved with other markets; reversing spikes undo themselves next month and may be recording errors. All stay in the data.">
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="border-b border-line text-left text-xs text-ink-3">
                      <th className="py-2 font-medium">Series</th>
                      <th className="py-2 font-medium">Month</th>
                      <th className="py-2 text-right font-medium">Log change</th>
                      <th className="py-2 font-medium">&nbsp;Classification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.extremes.slice(0, 200).map((e, i) => {
                      const s = q.series.find((x) => x.series_id === e.series_id);
                      return (
                        <tr key={i} className="border-b border-line/60 last:border-0">
                          <td className="py-1.5 text-ink-2">
                            <Link className="hover:text-rain" href={`/market?series=${String(e.series_id)}`}>
                              {s ? `${s.market_name} · ${s.commodity_name}` : String(e.series_id)}
                            </Link>
                          </td>
                          <td className="py-1.5 text-ink-2">{month(String(e.period))}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-2">{(Number(e.dlog) * 100).toFixed(1)}%</td>
                          <td className="py-1.5 text-ink-2">&nbsp;{String(e.classification).replace(/_/g, " ")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Dataset snapshots" note="Every ingestion writes an immutable snapshot with a content hash. Experiments record the snapshots they used.">
          {snapshots.isLoading && <Loading />}
          {snapshots.data && !snapshots.data.length && <Empty>No snapshots yet.</Empty>}
          <ul className="max-h-80 divide-y divide-line overflow-auto text-sm">
            {snapshots.data?.slice(0, 40).map((s) => (
              <li key={s.snapshot_id + s.dataset} className="py-2">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-ink">{s.dataset}</span>
                  <span className="tabular-nums text-ink-3">{s.row_count.toLocaleString()} rows</span>
                </div>
                <div className="text-xs text-ink-3">
                  {s.snapshot_id} · {s.providers.join(", ")} · hash {s.content_hash.slice(0, 12)}
                  {s.synthetic && " · synthetic"}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Ingestion log" note="Recent provider requests, with outcome and warnings. Credentials are never recorded.">
          {jobs.isLoading && <Loading />}
          {jobs.data && !jobs.data.length && <Empty>No ingestion jobs in this mode.</Empty>}
          <ul className="max-h-80 divide-y divide-line overflow-auto text-sm">
            {jobs.data?.slice(0, 40).map((j) => (
              <li key={j.id} className="py-2">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-ink">
                    {j.provider_id} · {j.dataset}
                  </span>
                  <Tag tone={j.status === "succeeded" ? "good" : j.status === "failed" ? "warn" : "muted"}>{j.status}</Tag>
                </div>
                <div className="text-xs text-ink-3">
                  {dateTime(j.started_at)} · {j.rows ?? 0} rows{j.requests_made != null && ` · ${j.requests_made} requests`}
                  {j.error && ` · ${j.error}`}
                  {j.warnings.length > 0 && ` · ${j.warnings.length} warnings`}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
