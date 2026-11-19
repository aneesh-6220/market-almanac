"use client";

import { ArrowRight, BookOpen } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { signedPct } from "@/components/market-bits";
import { cn, Empty, ErrorState, Field, inputClass, Loading, Note, PageHeader, Panel, Select, Tag } from "@/components/ui";
import { ApiError, loadingLabel } from "@/lib/api";
import { month } from "@/lib/format";
import { useGlobalCountries } from "@/lib/global-api";
import {
  EXTENT_LABEL,
  FLAG_LABEL,
  KIND_LABEL,
  type Shock,
  type ShockParams,
  useShockFacets,
  useShocks,
  WITHHELD_LABEL,
  zText,
} from "@/lib/investigation-api";
import { useUrlState } from "@/lib/url-state";

import { EXAMPLE } from "./example";

const PAGE = 25;

const KIND_OPTIONS = [
  { value: "unusual", label: "Unusual for the market" },
  { value: "large_typical", label: "Large but typical (25%+)" },
  { value: "withheld", label: "Large, not assessable" },
  { value: "all", label: "All of these" },
];
const DIRECTION_OPTIONS = [
  { value: "up", label: "Rises" },
  { value: "down", label: "Falls" },
  { value: "any", label: "Rises and falls" },
];
const EXTENT_OPTIONS = [
  { value: "widespread", label: "Widespread" },
  { value: "mixed", label: "Mixed" },
  { value: "local", label: "Local" },
  { value: "inconclusive", label: "Inconclusive" },
];
const SORT_OPTIONS = [
  { value: "recent", label: "Most recent peak" },
  { value: "unusual", label: "Most unusual rise" },
  { value: "unusual_down", label: "Most unusual fall" },
  { value: "change", label: "Largest 12-month rise" },
  { value: "change_down", label: "Largest 12-month fall" },
  { value: "duration", label: "Longest" },
];
const COVERAGE_OPTIONS = [
  { value: "0.5", label: "At least 50% observed" },
  { value: "0.75", label: "At least 75% observed" },
  { value: "0.9", label: "At least 90% observed" },
];

export function Discovery() {
  const { get, set } = useUrlState();
  const country = get("country");
  const kind = get("kind") || "unusual";
  const direction = get("dir") || "up";
  const page = Math.max(0, Number(get("page") || 0) || 0);
  const [q, setQ] = useState(get("q"));

  const params: ShockParams = {
    country: country || undefined,
    commodity: get("commodity") || undefined,
    q: get("q").length >= 2 ? get("q") : undefined,
    kind,
    direction,
    extent: get("extent") || undefined,
    peak_from: get("from") || undefined,
    peak_to: get("to") || undefined,
    min_coverage: get("cov") ? Number(get("cov")) : undefined,
    include_data_concerns: get("concerns") === "1" || undefined,
    include_non_food: get("nonfood") === "1" || undefined,
    stable_only: get("stable") === "1" || undefined,
    sort: get("sort") || "recent",
    limit: PAGE,
    offset: page * PAGE,
  };
  const shocks = useShocks(params);
  const countries = useGlobalCountries();
  const facets = useShockFacets(country || undefined);

  const countryOptions = useMemo(
    () => (countries.data?.countries ?? []).map((c) => ({ value: c.country_iso3, label: c.name })).sort((a, b) => a.label.localeCompare(b.label)),
    [countries.data],
  );
  const filter = (patch: Record<string, string | null>) => set({ ...patch, page: null });
  const d = shocks.data;

  return (
    <div>
      <PageHeader
        title="Price shock investigator"
        lede="Find food-price movements that were unusual for the market where they happened, then investigate one: how unusual, how lasting, whether comparable markets and other foods moved too, and what the data can and cannot say about why."
      />

      <div className="mb-6 grid gap-4 md:grid-cols-[1fr_auto]">
        <Note>
          A movement is <strong>unusual</strong> when its 12-month change sits at least 2 robust standard deviations from that
          series&apos; own earlier 12-month changes. A large change is not automatically unusual: in a market with high
          inflation, +40% a year can be ordinary. Series without enough history are listed as <em>not assessable</em>, never scored.
        </Note>
        <Link
          href={EXAMPLE.href}
          className="flex items-center gap-3 rounded-md border border-line bg-surface p-4 text-sm hover:bg-surface-2 md:max-w-xs"
        >
          <BookOpen className="h-5 w-5 shrink-0 text-rain" aria-hidden />
          <span>
            <span className="block font-medium text-ink">Worked example</span>
            <span className="text-ink-2">{EXAMPLE.title}</span>
          </span>
        </Link>
      </div>

      <Panel title="Filters" className="mb-6">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            filter({ q: q.trim().length >= 2 ? q.trim() : null });
          }}
        >
          <Field label="Country" htmlFor="f-country">
            <Select id="f-country" value={country} onChange={(v) => filter({ country: v || null, commodity: null })} options={countryOptions} placeholder="All 95 countries" />
          </Field>
          <Field label="Commodity" htmlFor="f-commodity">
            <Select
              id="f-commodity"
              value={get("commodity")}
              onChange={(v) => filter({ commodity: v || null })}
              options={(facets.data?.commodities ?? []).map((c) => ({ value: c.value, label: `${c.label} (${c.n})` }))}
              placeholder={country ? "All commodities" : "Choose a country first"}
            />
          </Field>
          <Field label="Search market, region or food" htmlFor="f-q">
            <input id="f-q" className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => filter({ q: q.trim().length >= 2 ? q.trim() : null })} placeholder="e.g. maize, Kano" maxLength={60} />
          </Field>
          <Field label="Kind of movement" htmlFor="f-kind">
            <Select id="f-kind" value={kind} onChange={(v) => filter({ kind: v === "unusual" ? null : v })} options={KIND_OPTIONS} />
          </Field>
          <Field label="Direction" htmlFor="f-dir">
            <Select id="f-dir" value={direction} onChange={(v) => filter({ dir: v === "up" ? null : v })} options={DIRECTION_OPTIONS} />
          </Field>
          <Field label="Comparable markets" htmlFor="f-extent">
            <Select id="f-extent" value={get("extent")} onChange={(v) => filter({ extent: v || null })} options={EXTENT_OPTIONS} placeholder="Any extent" />
          </Field>
          <Field label="Peak from" htmlFor="f-from">
            <input id="f-from" type="month" className={inputClass} value={get("from")} onChange={(e) => filter({ from: e.target.value || null })} />
          </Field>
          <Field label="Peak to" htmlFor="f-to">
            <input id="f-to" type="month" className={inputClass} value={get("to")} onChange={(e) => filter({ to: e.target.value || null })} />
          </Field>
          <Field label="Months observed around the episode" htmlFor="f-cov">
            <Select id="f-cov" value={get("cov")} onChange={(v) => filter({ cov: v || null })} options={COVERAGE_OPTIONS} placeholder="Any completeness" />
          </Field>
          <Field label="Sort" htmlFor="f-sort">
            <Select id="f-sort" value={get("sort") || "recent"} onChange={(v) => filter({ sort: v === "recent" ? null : v })} options={SORT_OPTIONS} />
          </Field>
          <fieldset className="flex flex-col justify-end gap-1.5 text-sm text-ink-2 sm:col-span-2">
            <legend className="sr-only">Quality</legend>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={get("stable") === "1"} onChange={(e) => filter({ stable: e.target.checked ? "1" : null })} />
              Only series with 60+ earlier changes (stable reference)
            </label>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={get("nonfood") === "1"} onChange={(e) => filter({ nonfood: e.target.checked ? "1" : null })} />
              Include non-food items (fuel, exchange rates, medicines, wages)
            </label>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" checked={get("concerns") === "1"} onChange={(e) => filter({ concerns: e.target.checked ? "1" : null })} />
              Include possible recording or unit errors
            </label>
          </fieldset>
        </form>
      </Panel>

      {shocks.isPending ? (
        <Loading label={loadingLabel(shocks, "Loading price movements")} />
      ) : shocks.isError && shocks.error instanceof ApiError && shocks.error.status === 501 ? (
        <Empty>
          The list of price movements is not installed on this deployment yet; it ships with the next price data release.
          Investigations still work: open the <Link href={EXAMPLE.href} className="underline">worked example</Link>, or use
          &ldquo;Investigate a price movement&rdquo; on any <Link href="/explorer" className="underline">market page</Link>.
        </Empty>
      ) : shocks.isError ? (
        <ErrorState error={shocks.error} what="price movements" />
      ) : d && d.items.length === 0 ? (
        <Empty>
          No movements match these filters. Try another kind of movement, a wider period, or including possible recording errors.
        </Empty>
      ) : d ? (
        <Panel
          title={`${d.total.toLocaleString("en")} ${d.total === 1 ? "episode" : "episodes"}`}
          note={
            <>
              Method {d.method_version ?? "—"}
              {d.built_at && <> · computed {month(d.built_at)}</>}
              {d.stale_countries.length > 0 && <> · {d.stale_countries.length} countries have newer prices than these results</>}
            </>
          }
          className={cn(shocks.isPlaceholderData && "opacity-60")}
        >
          <ShockTable items={d.items} />
          <Pager total={d.total} page={page} onPage={(p) => set({ page: p ? String(p) : null })} />
          <p className="mt-4 text-xs text-ink-3">{d.definitions.caution}</p>
        </Panel>
      ) : null}
    </div>
  );
}

function ShockTable({ items }: { items: Shock[] }) {
  return (
    <div className="relative -mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[760px] text-sm">
        <caption className="sr-only">Price movement episodes</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th scope="col" className="py-2 pr-3 font-medium">Market and food</th>
            <th scope="col" className="py-2 pr-3 font-medium">Peak</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">12-month change</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium" title="Robust z-score against the series' own earlier 12-month changes">
              Unusualness
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Months</th>
            <th scope="col" className="py-2 pr-3 font-medium">Comparable markets</th>
            <th scope="col" className="py-2 font-medium">
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={`${s.series_id}-${s.start}-${s.kind}`} className="border-b border-line/60 align-top">
              <td className="py-2.5 pr-3">
                <div className="font-medium text-ink">
                  {s.commodity_name} <span className="font-normal text-ink-3">· {s.market_name}</span>
                </div>
                <div className="text-xs text-ink-3">
                  {[s.admin1_name, s.country_name ?? s.country_iso3].filter(Boolean).join(", ")} · {s.price_type}, {s.currency}/{s.unit}
                </div>
                {(s.data_concern || s.kind !== "unusual") && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {s.kind !== "unusual" && <Tag tone={KIND_LABEL[s.kind]?.tone}>{KIND_LABEL[s.kind]?.text ?? s.kind}</Tag>}
                    {s.data_concern && <Tag tone="warn">Possible data error</Tag>}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-3 whitespace-nowrap text-ink-2">{month(s.peak)}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-ink">{signedPct(s.peak_yoy_pct, 0)}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums">
                {s.peak_z == null ? (
                  <span className="text-xs text-ink-3" title={s.withheld_reason ? `Not assessed: ${WITHHELD_LABEL[s.withheld_reason] ?? s.withheld_reason}` : undefined}>
                    not assessed
                  </span>
                ) : (
                  <span className="text-ink">
                    z {zText(s.peak_z)}
                    {s.n_reference != null && (
                      <span className="block text-xs text-ink-3">
                        {s.peak_percentile === 1 || s.peak_percentile === 0 ? `${s.peak_percentile === 1 ? "above" : "below"} all ` : "vs "}
                        {s.n_reference} earlier changes
                      </span>
                    )}
                  </span>
                )}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-ink-2">
                {s.duration_months}
                {s.ongoing ? "+" : ""}
              </td>
              <td className="py-2.5 pr-3 text-ink-2">
                {s.extent ? (
                  <>
                    {EXTENT_LABEL[s.extent] ?? s.extent}
                    {s.peer_assessable != null && s.peer_assessable > 0 && (
                      <span className="block text-xs text-ink-3">
                        {s.peer_elevated} of {s.peer_assessable} assessable also unusual
                        {s.peer_assessable < 3 && " (too few to judge)"}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-ink-3">—</span>
                )}
              </td>
              <td className="py-2.5 text-right">
                <Link
                  href={`/investigate?series=${s.series_id}&event=${s.peak}`}
                  className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-line px-2 py-1 text-xs text-ink hover:bg-surface-2"
                  aria-label={`Investigate ${s.commodity_name} in ${s.market_name}, ${month(s.peak)}`}
                >
                  Investigate <ArrowRight className="h-3 w-3" aria-hidden />
                </Link>
                {s.flags.length > 0 && (
                  <span className="sr-only">Flags: {s.flags.map((f) => FLAG_LABEL[f] ?? f).join("; ")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pager({ total, page, onPage }: { total: number; page: number; onPage: (p: number) => void }) {
  const pages = Math.ceil(Math.min(total, 10_000) / PAGE);
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pages" className="mt-4 flex items-center justify-between gap-3 text-sm">
      <button type="button" disabled={page === 0} onClick={() => onPage(page - 1)} className="rounded border border-line px-3 py-1.5 disabled:opacity-40">
        Previous
      </button>
      <span className="text-ink-3">
        Page {page + 1} of {pages.toLocaleString("en")}
      </span>
      <button type="button" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)} className="rounded border border-line px-3 py-1.5 disabled:opacity-40">
        Next
      </button>
    </nav>
  );
}
