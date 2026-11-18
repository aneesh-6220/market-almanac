"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo } from "react";

import {
  Empty,
  ErrorState,
  Field,
  inputClass,
  Loading,
  Note,
  PageHeader,
  Panel,
  Select,
  Stat,
  Tag,
} from "@/components/ui";
import { dateTime, download, month, pct, toCsv } from "@/lib/format";
import {
  type CoverageStatus,
  type RegistryRow,
  STATUS_ORDER,
  STATUS_STYLE,
  useCountryRecord,
  useMarketIndex,
  useRegistry,
} from "@/lib/research-api";
import { useUrlState } from "@/lib/url-state";

const CoverageMap = dynamic(
  () => import("@/components/coverage-map").then((m) => m.CoverageMap),
  {
    ssr: false,
    loading: () => <Loading label="Loading map" />,
  },
);

const n = (v: number | null | undefined) =>
  typeof v === "number" ? v.toLocaleString("en") : "—";

function StatusPill({ s }: { s: CoverageStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-ink">
      <span
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ background: STATUS_STYLE[s].color }}
        aria-hidden
      />
      {STATUS_STYLE[s].label}
    </span>
  );
}

function CountryDetail({ iso3 }: { iso3: string }) {
  const rec = useCountryRecord(iso3);
  if (rec.isLoading) return <Loading label={`Loading ${iso3}`} />;
  if (rec.error)
    return <ErrorState error={rec.error} what={`the record for ${iso3}`} />;
  const r = rec.data;
  if (!r) return null;
  const qc = r.qc ?? {};
  const env = r.environment ?? {};
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold text-ink">
          {r.name} <span className="text-ink-3">({r.country_iso3})</span>
        </h3>
        <StatusPill s={r.status} />
      </div>
      {r.observations ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Observations" value={n(r.observations)} />
            <Stat label="Series" value={n(r.series)} />
            <Stat label="Markets" value={n(r.markets)} />
            <Stat
              label="Eligible series"
              value={n(r.eligible_series)}
              hint="48+ months, 80% coverage"
            />
          </div>
          <dl className="grid grid-cols-[10rem_minmax(0,1fr)] gap-x-3 gap-y-1.5">
            <dt className="text-ink-3">Period</dt>
            <dd>
              {month(r.first_period)} – {month(r.last_period)}
            </dd>
            <dt className="text-ink-3">Currencies</dt>
            <dd>{(r.currencies ?? []).join(", ") || "—"}</dd>
            <dt className="text-ink-3">Price types</dt>
            <dd>{(r.price_types ?? []).join(", ") || "—"}</dd>
            <dt className="text-ink-3">Market coordinates</dt>
            <dd>{pct(r.market_coordinate_completeness)} of markets</dd>
            <dt className="text-ink-3">Quality checks</dt>
            <dd>
              {qc.validated ? (
                <Tag tone="good">passed</Tag>
              ) : (
                <Tag tone="warn">blocking issue</Tag>
              )}{" "}
              <span className="text-ink-3">
                {n(qc.invalid_prices)} invalid · {n(qc.conflicting_duplicates)}{" "}
                conflicting duplicates · {n(qc.future_dated)} future-dated
              </span>
              {(qc.blocking ?? []).map((b: string) => (
                <div key={b} className="text-warn">
                  {b}
                </div>
              ))}
            </dd>
            <dt className="text-ink-3">Market-local weather</dt>
            <dd>
              {env.nasa_power_cells_stored
                ? `${env.nasa_power_cells_stored} NASA POWER grid cells stored`
                : "not extracted yet"}
            </dd>
            <dt className="text-ink-3">CHIRPS v3 band</dt>
            <dd>
              {env.chirps_v3_markets_in_band ?? "—"} markets within 50°S–50°N
              <span className="text-ink-3">
                {" "}
                (CHIRPS is not integrated in this release)
              </span>
            </dd>
            <dt className="text-ink-3">Macro / agriculture</dt>
            <dd>
              {r.macro_ingested ? "macro ingested" : "macro not ingested"} ·{" "}
              {r.agriculture_ingested
                ? "FAOSTAT ingested"
                : "FAOSTAT not ingested"}
            </dd>
            <dt className="text-ink-3">Snapshot</dt>
            <dd className="break-all font-mono text-xs">
              {r.snapshot?.snapshot_id} · sha256{" "}
              {String(r.snapshot?.file_sha256 ?? "").slice(0, 16)}…
            </dd>
            <dt className="text-ink-3">Last refresh</dt>
            <dd>{dateTime(r.last_successful_refresh)}</dd>
          </dl>
          {r.eligible_by_commodity.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium text-ink-3">
                Most eligible commodity groups
              </div>
              <ul className="space-y-0.5">
                {r.eligible_by_commodity.map((g, i) => (
                  <li key={i}>
                    {String(g.commodity_name)} · {String(g.unit)} ·{" "}
                    {String(g.price_type)} · {String(g.currency)}:{" "}
                    <span className="font-medium">
                      {String(g.eligible_series)}
                    </span>{" "}
                    eligible series
                  </li>
                ))}
              </ul>
            </div>
          )}
          {r.evaluations.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium text-ink-3">
                Out-of-sample evaluations
              </div>
              <ul className="space-y-0.5">
                {r.evaluations.slice(0, 6).map((e) => (
                  <li key={String(e.id)}>
                    {String(e.study ?? "experiment")} ·{" "}
                    {String(e.evidence_class)} · verdict{" "}
                    {String(e.verdict ?? "—")}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-ink-3">{r.licence}</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-3">
            {r.known_restrictions.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </>
      ) : (
        <Empty>
          {r.status === "unsupported"
            ? "No integrated price provider reports market prices for this country or territory. The map is blank here because there is no data, not because data were left out."
            : "The provider reports coverage, but no observations are stored yet."}
        </Empty>
      )}
    </div>
  );
}

export function AtlasClient() {
  const reg = useRegistry();
  const idx = useMarketIndex();
  const { get, set } = useUrlState();
  const status = get("status");
  const q = get("q");
  const selected = get("country") || undefined;

  const rows = useMemo(() => {
    const all = reg.data?.countries ?? [];
    return all
      .filter((r) =>
        status ? r.status === status : r.status !== "unsupported",
      )
      .filter(
        (r) =>
          !q ||
          r.name.toLowerCase().includes(q.toLowerCase()) ||
          r.country_iso3 === q.toUpperCase(),
      )
      .sort(
        (a, b) =>
          STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
          (b.observations ?? 0) - (a.observations ?? 0),
      );
  }, [reg.data, status, q]);
  const statusByCountry = useMemo(
    () =>
      Object.fromEntries(
        (reg.data?.countries ?? []).map((r) => [r.country_iso3, r.status]),
      ) as Record<string, CoverageStatus>,
    [reg.data],
  );

  const header = (
    <PageHeader
      title="Global coverage"
      lede={
        <>
          Every country and territory, with what is actually stored and checked
          for it. A country is coloured only when its prices are ingested; blank
          areas have no integrated price source. Market-level prices are
          WFP&apos;s; national statistics are context, not market observations.
        </>
      }
    />
  );
  if (reg.isLoading)
    return (
      <div>
        {header}
        <Loading label="Loading the coverage registry" />
      </div>
    );
  if (reg.error)
    return (
      <div>
        {header}
        <ErrorState error={reg.error} what="the coverage registry" />
      </div>
    );
  const d = reg.data!;

  return (
    <div>
      {header}

      <div className="mb-6 grid grid-cols-2 gap-4 rounded-md border border-line bg-surface p-5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat
          label="Countries with prices"
          value={n(d.totals.countries_with_observations)}
          hint={`of ${d.discovery.countries} WFP reports`}
        />
        <Stat label="Monthly observations" value={n(d.totals.observations)} />
        <Stat label="Price series" value={n(d.totals.series)} />
        <Stat label="Markets" value={n(d.totals.markets)} />
        <Stat
          label="Research-eligible series"
          value={n(d.totals.eligible_series)}
        />
        <Stat
          label="Registry built"
          value={dateTime(d.generated_at)}
          hint={
            d.source === "packaged" ? "copy shipped with the code" : undefined
          }
        />
      </div>

      <div
        className="mb-4 flex flex-wrap gap-2"
        role="group"
        aria-label="Filter countries by status"
      >
        {STATUS_ORDER.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => set({ status: status === s ? null : s })}
            title={d.status_definitions[s]}
            className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-sm ${status === s ? "border-ink bg-surface-2" : "border-line bg-surface"}`}
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: STATUS_STYLE[s].color }}
              aria-hidden
            />
            {STATUS_STYLE[s].label}{" "}
            <span className="text-ink-3">{d.counts[s] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Panel
          title="Markets with stored prices"
          note={
            idx.data
              ? `${n(idx.data.rows.length)} markets with coordinates. Click a point for its country.`
              : undefined
          }
        >
          {idx.isLoading && <Loading label="Loading markets" />}
          {idx.error && (
            <ErrorState error={idx.error} what="the market index" />
          )}
          {idx.data && (
            <CoverageMap
              index={idx.data}
              statusByCountry={statusByCountry}
              selected={selected}
              onSelect={(c) => set({ country: c })}
            />
          )}
        </Panel>
        <Panel
          title={selected ? "Country record" : "Select a country"}
          note={
            selected
              ? undefined
              : "Choose a country on the map or in the table."
          }
        >
          {selected ? (
            <CountryDetail iso3={selected} />
          ) : (
            <Empty>No country selected.</Empty>
          )}
        </Panel>
      </div>

      <Panel
        className="mt-6"
        title="Countries"
        note={
          status
            ? d.status_definitions[status]
            : "All countries with a reported price source. Use the status filters to see the others."
        }
        actions={
          <button
            type="button"
            className="rounded border border-line px-3 py-1.5 text-sm text-ink hover:bg-surface-2"
            onClick={() =>
              download(
                "coverage_registry.csv",
                toCsv(rows as unknown as Record<string, unknown>[]),
              )
            }
          >
            Download CSV
          </button>
        }
      >
        <div className="mb-3 flex flex-wrap gap-3">
          <Field label="Search" htmlFor="q">
            <input
              id="q"
              className={inputClass}
              value={q}
              placeholder="Country or ISO3"
              onChange={(e) => set({ q: e.target.value || null })}
            />
          </Field>
          <Field label="Status" htmlFor="status">
            <Select
              id="status"
              value={status}
              onChange={(v) => set({ status: v || null })}
              placeholder="With a price source"
              options={STATUS_ORDER.map((s) => ({
                value: s,
                label: `${STATUS_STYLE[s].label} (${d.counts[s] ?? 0})`,
              }))}
            />
          </Field>
        </div>
        {rows.length === 0 ? (
          <Empty>No countries match.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-sm">
              <caption className="sr-only">Coverage status by country</caption>
              <thead className="text-left text-xs text-ink-3">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-3">
                    Country
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Status
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Markets
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Series
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Observations
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Eligible
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    Period
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Coordinates
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: RegistryRow) => (
                  <tr
                    key={r.country_iso3}
                    className={`border-b border-line/60 ${selected === r.country_iso3 ? "bg-surface-2" : ""}`}
                  >
                    <th
                      scope="row"
                      className="py-1.5 pr-3 text-left font-normal"
                    >
                      <button
                        type="button"
                        className="text-rain underline-offset-4 hover:underline"
                        onClick={() => set({ country: r.country_iso3 })}
                      >
                        {r.name}
                      </button>{" "}
                      <span className="text-ink-3">{r.country_iso3}</span>
                    </th>
                    <td className="py-1.5 pr-3">
                      <StatusPill s={r.status} />
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {n(r.markets)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {n(r.series)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {n(r.observations)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {n(r.eligible_series)}
                    </td>
                    <td className="py-1.5 pr-3">
                      {r.first_period
                        ? `${month(r.first_period)} – ${month(r.last_period)}`
                        : "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {pct(r.market_coordinate_completeness)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Note>
        Status definitions:{" "}
        {Object.entries(d.status_definitions)
          .map(
            ([k, v]) =>
              `${STATUS_STYLE[k as CoverageStatus]?.label ?? k}: ${v}`,
          )
          .join(" ")}{" "}
        See{" "}
        <Link href="/data" className="underline">
          Data &amp; provenance
        </Link>{" "}
        for provider licences.
      </Note>
    </div>
  );
}
