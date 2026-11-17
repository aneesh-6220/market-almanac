"use client";

import { ArrowDownRight, ArrowUpRight, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { signedPct } from "@/components/market-bits";
import { ErrorState, inputClass, Loading } from "@/components/ui";
import { fmt, month } from "@/lib/format";
import { useCoverageSummary, useMovers } from "@/lib/market-api";
import { useStatus } from "@/lib/queries";

export function HomeSearch() {
  const [q, setQ] = useState("");
  const router = useRouter();
  return (
    <form
      role="search"
      className="mt-8 flex max-w-xl gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(q.trim().length >= 2 ? `/explorer?q=${encodeURIComponent(q.trim())}&country=` : "/explorer");
      }}
    >
      <label htmlFor="home-q" className="sr-only">
        Search markets and commodities
      </label>
      <input id="home-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a market or commodity, e.g. maize, Niamey" className={`${inputClass} h-11 w-full text-base`} />
      <button type="submit" className="inline-flex h-11 items-center gap-2 rounded bg-ink px-4 text-sm font-medium text-bg hover:bg-ink-2">
        <Search className="h-4 w-4" aria-hidden /> Explore
      </button>
    </form>
  );
}

export function HomeCoverage() {
  const cov = useCoverageSummary();
  const status = useStatus();
  if (cov.isLoading) return <Loading label="Loading coverage" />;
  if (cov.isError) return <ErrorState error={cov.error} what="coverage" />;
  const t = cov.data?.totals ?? {};
  const n = (k: string) => (typeof t[k] === "number" ? (t[k] as number).toLocaleString() : "—");
  return (
    <div className="rounded-md border border-line bg-surface p-5 md:p-7" data-testid="home-coverage">
      <div className="text-sm text-ink-3">{status.data?.synthetic ? "Demo dataset (synthetic)" : "In this deployment"}</div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
        {[
          ["Countries", n("countries")],
          ["Markets", n("markets")],
          ["Series with 12+ months", n("usable_series")],
          ["Monthly prices", n("observations")],
        ].map(([k, v]) => (
          <div key={k}>
            <dd className="font-serif text-3xl text-ink">{v}</dd>
            <dt className="mt-0.5 text-sm text-ink-3">{k}</dt>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-sm text-ink-2">
        Newest observation: {month(t.last_period as string)}. {n("forecast_evaluated_series")} series are covered by a forecast evaluation; the rest are price history only.
      </p>
      <ul className="mt-4 flex flex-wrap gap-2">
        {(cov.data?.countries ?? []).map((c) => (
          <li key={c.country_iso3}>
            <Link href={`/explorer?country=${c.country_iso3}`} className="inline-flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-sm text-ink hover:bg-surface-2">
              {c.name} <span className="text-xs text-ink-3">{c.usable_series.toLocaleString()}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HomeMovers() {
  const movers = useMovers({ limit: 8 });
  if (movers.isLoading) return <Loading label="Loading recent movements" />;
  if (movers.isError) return <ErrorState error={movers.error} what="recent movements" />;
  if (!movers.data?.length) return <p className="text-sm text-ink-3">No series currently shows an unusual latest movement.</p>;
  return (
    <ul className="divide-y divide-line border-y border-line" data-testid="home-movers">
      {movers.data.map(({ series: s, direction }) => {
        const Icon = direction === "up" ? ArrowUpRight : ArrowDownRight;
        return (
          <li key={s.series_id}>
            <Link href={`/market?series=${s.series_id}`} className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-3 py-3 hover:bg-surface-2/60">
              <Icon className={`h-4 w-4 ${direction === "up" ? "text-grain" : "text-rain"}`} aria-hidden />
              <span className="min-w-0">
                <span className="block truncate font-medium text-ink">
                  {s.commodity_name} · {s.market_name}
                </span>
                <span className="block truncate text-sm text-ink-3">
                  {s.country_iso3} · {fmt(s.latest_price)} {s.currency}/{s.unit} · observed {month(s.last_period)}
                </span>
              </span>
              <span className="text-right">
                <span className="block font-medium text-ink">{signedPct(s.change_1m)}</span>
                <span className="block text-xs text-ink-3">
                  larger than {s.movement_percentile == null ? "—" : `${Math.floor(s.movement_percentile * 100)}%`} of {s.movement_n_reference} past moves
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
