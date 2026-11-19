"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiGet, apiUrl } from "./api";

/* Price Shock Investigator: discovery of unusual movements and single-series investigations. */

const num = z.number().nullable();
const str = z.string().nullable();
const long = { staleTime: 10 * 60_000 };

export const KINDS = ["unusual", "large_typical", "withheld", "all"] as const;
export const DIRECTIONS = ["up", "down", "any"] as const;
export const EXTENTS = ["widespread", "mixed", "local", "inconclusive"] as const;
export const SORTS = ["unusual", "unusual_down", "change", "change_down", "recent", "duration"] as const;

export const KIND_LABEL: Record<string, { text: string; tone: "good" | "neutral" | "warn" | "muted" }> = {
  unusual: { text: "Unusual", tone: "warn" },
  large_typical: { text: "Large but typical", tone: "neutral" },
  withheld: { text: "Not assessed", tone: "muted" },
};

export const EXTENT_LABEL: Record<string, string> = {
  widespread: "Widespread",
  mixed: "Mixed",
  local: "Local",
  inconclusive: "Inconclusive",
  broad: "Broad",
  narrow: "Narrow",
};

export const FLAG_LABEL: Record<string, string> = {
  implausible_jump: "Implausible one-month jump (possible unit or recording change)",
  single_month_reversed: "Single month, fully reversed",
  possible_base_effect: "Possible base effect (unusual month a year earlier)",
  short_reference: "Fewer than 60 earlier changes",
  sparse_recent_record: "Sparse recent record",
  missing_months_inside: "Missing months inside the episode",
};

export const WITHHELD_LABEL: Record<string, string> = {
  short_history: "too short a history",
  few_years: "fewer than 4 years of history",
  sparse_recent: "too few recent observations",
  degenerate_history: "prices almost never changed before",
};

export const ShockSchema = z.object({
  series_id: z.string(),
  country_iso3: z.string(),
  country_name: z.string().optional(),
  market_code: str.optional(),
  market_name: z.string(),
  admin1_name: str.optional(),
  commodity_code: str.optional(),
  commodity_name: z.string(),
  unit: z.string(),
  price_type: z.string(),
  currency: z.string(),
  kind: z.string(),
  direction: z.string(),
  start: str,
  peak: str,
  end: str,
  duration_months: z.number(),
  ongoing: z.boolean().nullable().optional(),
  peak_yoy_pct: num,
  peak_z: num,
  peak_percentile: num,
  n_reference: num,
  stable: z.boolean().nullable().optional(),
  peak_index: num,
  window_coverage: num,
  flags: z.array(z.string()),
  data_concern: z.boolean(),
  withheld_reason: str,
  extent: str,
  peer_n: num,
  peer_assessable: num,
  peer_elevated: num,
  months_behind_dataset: num.optional(),
});
export type Shock = z.infer<typeof ShockSchema>;

export const ShockPageSchema = z.object({
  items: z.array(ShockSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  method_version: str,
  built_at: str,
  stale_countries: z.array(z.string()),
  definitions: z.record(z.string(), z.string()),
});
export type ShockPage = z.infer<typeof ShockPageSchema>;

const Facet = z.object({ value: z.string(), label: z.string(), n: z.number() });
export const FacetsSchema = z.object({
  country_iso3: z.string(),
  commodities: z.array(Facet),
  markets: z.array(Facet),
  price_types: z.array(Facet),
  units: z.array(Facet),
  years: z.array(Facet),
});
export type Facets = z.infer<typeof FacetsSchema>;

const Episode = z.object({
  kind: z.string(),
  direction: z.string(),
  start: z.string(),
  peak: z.string(),
  end: z.string(),
  duration_months: z.number(),
  ongoing: z.boolean(),
  peak_price: num,
  peak_yoy_pct: num,
  peak_z: num,
  peak_percentile: num,
  n_reference: num,
  stable: z.boolean().nullable(),
  peak_index: num,
  retrace_6m_pct: num,
  window_coverage: num,
  flags: z.array(z.string()),
  data_concern: z.boolean(),
  withheld_reason: str,
});
export type Episode = z.infer<typeof Episode>;

const Extent = z.object({
  class: z.string(),
  n_peers: z.number(),
  n_assessable: z.number(),
  n_elevated: z.number(),
  share_elevated: num,
  share_same_direction: num.optional(),
  n_with_change: z.number().optional(),
  median_peer_yoy_pct: num,
  rule: z.string(),
});

const PeerRow = z.object({
  series_id: z.string(),
  market_name: z.string(),
  admin1_name: str.optional(),
  commodity_name: z.string(),
  unit: z.string(),
  price_type: z.string(),
  status: z.string(),
  reason: str,
  period: str,
  yoy_pct: num,
  z: num,
  elevated: z.boolean().nullable(),
});
export type PeerRow = z.infer<typeof PeerRow>;

const Inference = z.object({ text: z.string(), inference: z.string(), evidence: z.array(z.string()) });
export type InferenceItem = z.infer<typeof Inference>;

const MacroIndicator = z.object({
  indicator_code: z.string(),
  indicator_name: z.string(),
  unit: z.string(),
  provider: z.string(),
  period: z.string(),
  value: z.number(),
  yoy_pct: z.number(),
  series: z.array(z.object({ period: z.string(), value: z.number() })),
});

export const InvestigationSchema = z.object({
  config: z.object({
    format: z.string(),
    method_version: z.string(),
    series_id: z.string(),
    event: z.string(),
    window: z.object({ start: z.string(), end: z.string() }),
    peers: z.string(),
    snapshot_id: z.string(),
  }),
  config_id: z.string(),
  method: z.object({ version: z.string(), text: z.string() }),
  subject: z.object({
    series_id: z.string(),
    country_iso3: z.string(),
    country_name: z.string(),
    market_name: z.string(),
    admin1_name: str.optional(),
    admin2_name: str.optional(),
    commodity_name: z.string(),
    unit: z.string(),
    price_type: z.string(),
    price_flag: str.optional(),
    currency: z.string(),
    first_period: str,
    last_period: str,
    n_observations: z.number(),
  }),
  episode: Episode.nullable(),
  episodes_in_window: z.array(Episode),
  direction: z.string(),
  magnitude: z.object({
    event_price: num,
    event_yoy_pct: num,
    event_mom_pct: num,
    change_from_baseline_pct: num,
    peak_month: str,
    peak_price: num,
    peak_index: num,
    large_nominal: z.boolean(),
  }),
  unusualness: z.object({
    status: z.string(),
    z: num.optional(),
    percentile: num.optional(),
    n_reference: num.optional(),
    reference_years: num.optional(),
    reference_median_yoy_pct: num.optional(),
    reference_p10_yoy_pct: num.optional(),
    reference_p90_yoy_pct: num.optional(),
    band_upper_yoy_pct: num.optional(),
    band_lower_yoy_pct: num.optional(),
    label: str.optional(),
    stable: z.boolean().nullable().optional(),
    reference_ends: str.optional(),
    reason: str.optional(),
    text: str.optional(),
  }),
  persistence: z.object({
    verdict: z.string(),
    duration_months: num.optional(),
    ongoing: z.boolean().optional(),
    retrace_6m_pct: num.optional(),
    note: str.optional(),
  }),
  seasonality: z.object({
    status: z.string(),
    years_used: num.optional(),
    expected_change_pct: num.optional(),
    observed_change_pct: num.optional(),
    share_explained: num.optional(),
    verdict: str.optional(),
    peak_calendar_month: num.optional(),
    trough_calendar_month: num.optional(),
    seasonal_amplitude: num.optional(),
    months: z
      .array(z.object({ month: z.number(), name: z.string(), median_index: num, q25: num, q75: num, n_years: z.number() }))
      .optional(),
    method: str.optional(),
    reason: str.optional(),
  }),
  peers: z.object({
    extent: Extent,
    rows: z.array(PeerRow),
    index: z.object({
      base: z.object({ start: z.string(), end: z.string() }).nullable(),
      n_indexed_peers: z.number(),
      rows: z.array(
        z.object({ period: z.string(), own: num, peer_median: num, peer_q25: num, peer_q75: num, peers_observed: z.number() }),
      ),
    }),
    capped_at: z.number(),
    n_available: z.number().nullish(),
  }),
  breadth: z.object({
    extent: Extent,
    rows: z.array(PeerRow),
    capped_at: z.number(),
    n_available: z.number().nullish(),
  }),
  context: z.object({
    weather: z.object({
      status: z.string(),
      market_cell: z
        .object({
          months: z.number(),
          mean_rain_anomaly_z: num,
          months_rain_below_minus_1_5: z.number(),
          months_rain_above_1_5: z.number(),
          basis: str.optional(),
          window: z.object({ start: z.string(), end: z.string() }),
        })
        .nullable(),
      production_region: z
        .object({ crop: str, period: z.string(), season_rain_anomaly_z: num, min_season_rain_anomaly_z: num, basis: str.optional() })
        .nullable(),
      note: z.string().optional(),
    }),
    macro: z.object({ cpi: MacroIndicator.nullable(), fx: MacroIndicator.nullable(), real_yoy_pct: num, available: z.array(z.string()) }),
  }),
  observation_quality: z.object({
    months_in_window: z.number(),
    months_observed: z.number(),
    months_missing: z.number(),
    missing_months: z.array(z.string()),
    longest_gap_months: z.number(),
    records_in_window: z.number(),
    records_not_used: z.number(),
    flagged_records: z.array(z.object({ period: z.string(), price: num, flags: z.array(z.string()), used: z.boolean().nullable() })),
  }),
  signals: z.array(
    z.object({ period: z.string(), price: num, mom_pct: num, yoy_pct: num, z: num, percentile: num, status: z.string(), reason: str }),
  ),
  question: z.string(),
  evidence: z.object({
    observed_facts: z.array(Inference),
    quantitative: z.array(Inference),
    mechanisms: z.array(
      z.object({
        key: z.string(),
        name: z.string(),
        description: z.string(),
        status: z.string(),
        status_text: z.string(),
        evidence: z.array(z.string()),
        needed: z.array(z.string()),
        // evidence kept apart by kind (macro: nominal increases, historical unusualness, mechanism evidence, missing)
        evidence_groups: z.array(z.object({ key: z.string(), label: z.string(), items: z.array(z.string()) })).optional(),
      }),
    ),
    gaps: z.array(z.string()),
    unsupported: z.array(Inference),
    conclusion: z.object({ text: z.string(), inference: z.string() }),
    assessment: z.array(z.object({ key: z.string(), label: z.string(), value: z.string(), tone: z.string(), detail: str })),
    rules: z.object({ screening: str.optional(), episode: str.optional() }).passthrough().optional(),
  }),
  sources: z.array(z.object({ name: z.string(), use: z.string(), licence: z.string(), url: z.string() })),
});
export type Investigation = z.infer<typeof InvestigationSchema>;

export type ShockParams = {
  country?: string;
  commodity?: string;
  q?: string;
  price_type?: string;
  unit?: string;
  kind?: string;
  direction?: string;
  extent?: string;
  peak_from?: string;
  peak_to?: string;
  min_coverage?: number;
  include_data_concerns?: boolean;
  include_non_food?: boolean;
  stable_only?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
};

export const useShocks = (params: ShockParams) =>
  useQuery({
    queryKey: ["shocks", params],
    queryFn: () => apiGet("/api/v1/shocks", ShockPageSchema, params),
    placeholderData: keepPreviousData,
    ...long,
  });

export const useShockFacets = (country?: string) =>
  useQuery({
    queryKey: ["shock-facets", country],
    queryFn: () => apiGet("/api/v1/shocks/facets", FacetsSchema, { country }),
    enabled: !!country,
    ...long,
  });

/** `snapshot` pins the price snapshot: the API answers 409 rather than serve different data under that link. */
export type InvestigationParams = { event?: string; start?: string; end?: string; snapshot?: string };

export const useInvestigation = (id: string | undefined, params: InvestigationParams) =>
  useQuery({
    queryKey: ["investigation", id, params],
    queryFn: () => apiGet(`/api/v1/investigations/${id}`, InvestigationSchema, params),
    enabled: !!id,
    ...long,
  });

/** Robust z-scores beyond +/-10 only say "far outside every earlier change"; more digits would be false precision. */
export const zText = (z: number | null | undefined): string =>
  z == null || !Number.isFinite(z) ? "—" : Math.abs(z) >= 10 ? `beyond ${z > 0 ? "+" : "−"}10` : `${z > 0 ? "+" : ""}${z.toFixed(1)}`;

/** The configuration that reproduces a document exactly (snapshot aside, which the document records). */
export const configParams = (d: Investigation): Required<Omit<InvestigationParams, "snapshot">> => ({
  event: d.config.event,
  start: d.config.window.start,
  end: d.config.window.end,
});

/**
 * A link that names the price snapshot it was made from. Only the newest snapshot of a country is served, so after a
 * data revision the link reports the mismatch instead of silently showing different numbers. Without `pinned` it is
 * a live link: it loads whatever the site serves when it is opened.
 */
export function permalink(origin: string, d: Investigation, pinned = true): string {
  const p = configParams(d);
  const base = `${origin}/investigate?series=${d.config.series_id}&event=${p.event}&start=${p.start}&end=${p.end}`;
  return pinned ? `${base}&snapshot=${d.config.snapshot_id}` : base;
}

export function exportUrl(d: Investigation, format: "md" | "json" | "csv", opts: { table?: string; link?: string } = {}): string {
  return apiUrl(`/api/v1/investigations/${d.config.series_id}/export`, {
    ...configParams(d),
    snapshot: d.config.snapshot_id,
    format,
    ...opts,
  });
}
