"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiGet, apiUrl } from "./api";

/* Schemas and hooks for the public market-intelligence endpoints (catalog, series, compare, studies). */

const num = z.number().nullable();
const str = z.string().nullable();
const long = { staleTime: 5 * 60_000 };

export const CatalogSeriesSchema = z.object({
  series_id: z.string(),
  country_iso3: z.string(),
  market_code: z.string(),
  market_name: z.string(),
  admin1_name: str.optional(),
  lat: num.optional(),
  lon: num.optional(),
  commodity_code: z.string(),
  commodity_name: z.string(),
  commodity_category: str.optional(),
  unit: z.string(),
  price_type: z.string(),
  price_flag: z.string(),
  currency: z.string(),
  first_period: z.string(),
  last_period: z.string(),
  n_observations: z.number(),
  coverage: z.number(),
  longest_gap_months: z.number(),
  usable: z.boolean(),
  eligible: z.boolean(),
  ineligible_reasons: str.optional(),
  latest_price: num.optional(),
  change_1m: num.optional(),
  change_12m: num.optional(),
  movement_label: z.string(),
  movement_percentile: num.optional(),
  movement_n_reference: z.number(),
  months_behind_dataset: z.number(),
  has_weather: z.boolean(),
});
export type CatalogSeries = z.infer<typeof CatalogSeriesSchema>;

const page = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), limit: z.number(), offset: z.number(), snapshot_id: str, synthetic: z.boolean() });
export const CatalogPageSchema = page(CatalogSeriesSchema);

export const CatalogCommoditySchema = z.object({
  commodity_code: z.string(),
  commodity_name: z.string(),
  commodity_category: str,
  countries: z.array(z.string()),
  markets: z.number(),
  series: z.number(),
  usable_series: z.number(),
  units: z.array(z.string()),
  production_region_crop: str,
});
export type CatalogCommodity = z.infer<typeof CatalogCommoditySchema>;

export const CatalogMarketSchema = z.object({
  country_iso3: z.string(),
  market_code: z.string(),
  market_name: z.string(),
  admin1_name: str,
  lat: num,
  lon: num,
  series: z.number(),
  usable_series: z.number(),
  commodities: z.number(),
  last_period: z.string(),
  has_weather: z.boolean(),
});
export type CatalogMarket = z.infer<typeof CatalogMarketSchema>;

export const CoverageCountrySchema = z.object({
  country_iso3: z.string(),
  name: z.string(),
  markets: z.number(),
  commodities: z.number(),
  series: z.number(),
  usable_series: z.number(),
  eligible_series: z.number(),
  first_period: z.string(),
  last_period: z.string(),
  median_coverage_usable: num,
  series_updated_within_3_months: z.number(),
  currencies: z.array(z.string()),
  series_with_weather: z.number(),
  forecast_evaluated_series: z.number(),
  production_region_crops: z.array(z.string()),
  features: z.record(z.string(), z.boolean()),
});
export type CoverageCountry = z.infer<typeof CoverageCountrySchema>;
export const CoverageSummarySchema = z.object({
  countries: z.array(CoverageCountrySchema),
  totals: z.record(z.string(), z.union([z.number(), z.string()]).nullable()),
  definitions: z.record(z.string(), z.string()).optional(),
  scope_note: z.string().optional(),
  snapshot_id: str,
  synthetic: z.boolean(),
});

const ChangeSchema = z
  .object({ months: z.number(), reference_period: z.string(), reference_price: z.number(), pct_change: z.number(), abs_change: z.number() })
  .nullable();
export const SummarySchema = z
  .object({
    status: z.string(),
    latest_period: z.string().optional(),
    latest_price: z.number().optional(),
    first_period: z.string().optional(),
    n_observations: z.number(),
    months_spanned: z.number().optional(),
    coverage: z.number().optional(),
    missing_months_last_24: z.number().optional(),
    months_behind_dataset: num.optional(),
    changes: z.object({ m1: ChangeSchema, m3: ChangeSchema, m12: ChangeSchema }).optional(),
    range_12m: z.object({ min: z.number(), max: z.number(), min_period: z.string(), max_period: z.string(), n: z.number() }).optional(),
  })
  .passthrough();

export const SeriesDetailSchema = z.object({
  series: CatalogSeriesSchema,
  summary: SummarySchema,
  provenance: z.object({
    provider: z.string(),
    source_ref: str,
    snapshot_id: str,
    retrieved_at: str,
    attribution: z.string(),
    license_note: z.string(),
    observation_basis: z.string(),
  }),
  synthetic: z.boolean(),
});
export type SeriesDetail = z.infer<typeof SeriesDetailSchema>;

export const HistorySchema = z.object({
  series_id: z.string(),
  unit: z.string(),
  currency: z.string(),
  price_type: z.string(),
  items: z.array(z.object({ period: z.string(), price: num })),
  n_observed: z.number(),
  n_missing: z.number(),
  excluded_records: z.number(),
  snapshot_id: str,
  synthetic: z.boolean(),
});
export type History = z.infer<typeof HistorySchema>;

const Against = z
  .object({ n_reference: z.number(), percentile_of_size: num, robust_z: num, reference_median: num, reference_p10: num, reference_p90: num })
  .passthrough();
export const AssessmentSchema = z
  .object({
    status: z.string(),
    label: z.string(),
    method: z.string(),
    period: z.string().optional(),
    reference_period: z.string().optional(),
    span_months: z.number().optional(),
    price: z.number().optional(),
    reference_price: z.number().optional(),
    pct_change: z.number().optional(),
    direction: z.string().optional(),
    stable: z.boolean().optional(),
    warnings: z.array(z.string()).optional(),
    overall: Against.optional(),
    seasonal: Against.extend({ calendar_month: z.number() }).nullable().optional(),
    year_on_year: z.object({ pct_change: z.number(), percentile_of_size: num, n_reference: z.number(), label: z.string() }).passthrough().nullable().optional(),
    volatility: z.object({ window_months: z.number(), sd_log_change: z.number(), percentile: num, label: z.string(), n_reference: z.number() }).nullable().optional(),
  })
  .passthrough();
export type Assessment = z.infer<typeof AssessmentSchema>;

export const PeersSchema = z
  .object({
    status: z.string(),
    n_peers: z.number(),
    peer_median_pct_change: z.number().optional(),
    share_same_direction: z.number().optional(),
    reverses_next_month: z.boolean().nullable().optional(),
    pattern: z.string().optional(),
  })
  .nullable();

export const MovementSchema = z.object({
  series_id: z.string(),
  assessment: AssessmentSchema,
  peers: PeersSchema,
  history: z.array(z.object({ period: z.string(), pct_change: z.number(), percentile_of_size: z.number(), label: z.string(), n_reference: z.number() }).passthrough()),
  disclaimer: z.string(),
  snapshot_id: str,
});
export type Movement = z.infer<typeof MovementSchema>;

export const SeasonalitySchema = z
  .object({
    status: z.string(),
    months: z.array(z.object({ month: z.number(), name: z.string(), median_index: z.number(), q25: z.number(), q75: z.number(), n_years: z.number() })),
    years_used: z.number().optional(),
    peak_month: z.number().optional(),
    trough_month: z.number().optional(),
    seasonal_amplitude: z.number().optional(),
    method: z.string().optional(),
    note: z.string().optional(),
  })
  .passthrough();
export type Seasonality = z.infer<typeof SeasonalitySchema>;

export const EnvironmentSchema = z.object({
  series_id: z.string(),
  status: z.string(),
  market_cell: z
    .object({
      location_id: z.string(),
      lat: z.number(),
      lon: z.number(),
      period: z.string(),
      precip_total_mm: num,
      rain_anomaly_z: num,
      temp_anomaly_z: num,
      qc_flagged: z.boolean(),
      qc_flagged_months_last_24: z.number(),
      basis: z.string(),
    })
    .nullable(),
  market_cell_series: z.array(
    z.object({ period: z.string(), precip_total_mm: num, precip_total_mm_raw: num.optional(), rain_anomaly_z: num, temp_anomaly_z: num, qc_flagged_days: num.optional() }).passthrough(),
  ),
  production_region: z
    .object({
      crop: z.string(),
      period: z.string(),
      season_rain_anomaly_z: num,
      previous_season_rain_anomaly_z: num,
      season_heat_anomaly_z: num,
      in_season: z.boolean(),
      months_since_harvest: z.number(),
      season_months: z.array(z.number()),
      calendar_basis: z.string(),
      cells: z.number(),
      area_share_kept: num,
      basis: z.string(),
    })
    .nullable(),
  production_region_series: z.array(z.object({ period: z.string(), season_rain_anomaly_z: num, season_heat_anomaly_z: num, in_season: z.boolean() })),
  caveats: z.array(z.string()),
  sources: z.array(z.string()),
  snapshot_id: str,
});
export type Environment = z.infer<typeof EnvironmentSchema>;

export const BriefSchema = z.object({
  series_id: z.string(),
  title: z.string(),
  as_of_period: str,
  sentences: z.array(z.object({ section: z.string(), text: z.string() })),
  text: z.string(),
  evidence: z
    .object({
      forecast: z
        .object({ experiment_id: z.string(), status: z.string(), validation_status: z.string(), reason: str, horizon: z.number(), target_period: z.string(), origin_period: z.string() })
        .passthrough()
        .nullable()
        .optional(),
    })
    .passthrough(),
  method: z.string(),
  snapshot_id: str,
  synthetic: z.boolean(),
});
export type Brief = z.infer<typeof BriefSchema>;

export const CompareSchema = z.object({
  status: z.string(),
  comparability: z.object({ level: z.string(), absolute: z.boolean(), indexed: z.boolean(), reasons: z.array(z.string()) }).passthrough(),
  series_meta: z.array(CatalogSeriesSchema),
  window: z.object({ start: z.string(), end: z.string(), months: z.number() }).nullable().optional(),
  months_all_observed: num.optional(),
  index_base: z.object({ mode: z.string(), base_period: str, warning: z.string().optional() }).passthrough().nullable().optional(),
  series: z.array(
    z
      .object({
        series_id: z.string(),
        n_observations: z.number(),
        missing_share: z.number(),
        first_period: z.string(),
        last_period: z.string(),
        first_price: z.number(),
        last_price: z.number(),
        pct_change_over_window: z.number(),
        window_months: z.number(),
        last_index: num,
      })
      .passthrough(),
  ),
  latest_common_spread: z
    .object({ period: z.string(), min: z.number(), max: z.number(), max_over_min: z.number(), lowest_series: z.string(), highest_series: z.string() })
    .nullable()
    .optional(),
  pairs: z.array(z.object({ a: z.string(), b: z.string(), n: z.number(), correlation_of_monthly_changes: num })),
  rows: z.array(z.object({ period: z.string(), prices: z.record(z.string(), num), index: z.record(z.string(), num) })),
  caveats: z.array(z.string()),
  snapshot_id: str.optional(),
});
export type Compare = z.infer<typeof CompareSchema>;

export const MoverSchema = z.object({ series: CatalogSeriesSchema, direction: z.string() });

const StudyRow = z
  .object({
    country: z.string(),
    evidence_class: z.string(),
    variant: z.string(),
    contrast: z.string(),
    horizon: z.number(),
    n_rows: z.number(),
    n_months: z.number(),
    n_series: num.optional(),
    loss_ratio: num,
    ci_low: num,
    ci_high: num,
    p_b_better: num,
    p_holm: num.optional(),
    fragile: z.boolean().nullable().optional(),
    fragility_reasons: z.array(z.string()).nullable().optional(),
    commodity_code: z.string().optional(),
  })
  .passthrough();
export type StudyRow = z.infer<typeof StudyRow>;
export const StudySchema = z
  .object({
    study_id: z.string(),
    phase: z.string(),
    generated_at: z.string().optional(),
    spec: z.object({ horizons: z.array(z.number()), primary_lag: z.number(), alpha: z.number() }).passthrough(),
    experiments: z.array(
      z.object({ experiment_id: z.string(), country: z.string(), commodity_code: z.string(), commodity_name: z.string(), variant: z.string(), evidence_class: z.string(), n_series: z.number() }).passthrough(),
    ),
    pooled: z.array(StudyRow),
    per_crop: z.array(StudyRow),
    confirmatory: z.object({
      n_tests: z.number(),
      method: z.string(),
      decisions: z.array(
        z
          .object({
            country: z.string(),
            horizon: z.number(),
            contrast: z.string(),
            loss_ratio: num,
            p_one_sided: num,
            p_holm: num,
            holm_significant: z.boolean(),
            stable_in_both_halves: z.boolean(),
            beats_time_shift_placebo: z.boolean(),
            not_fragile: z.boolean(),
            outcome: z.string(),
          })
          .passthrough(),
      ),
      outcome: z.object({ label: z.string(), statement: z.string() }).passthrough(),
    }),
  })
  .passthrough();
export type Study = z.infer<typeof StudySchema>;

/* ---- hooks ---- */

export type CatalogParams = {
  country?: string;
  commodity?: string;
  market?: string;
  q?: string;
  usable_only?: boolean;
  eligible_only?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
};

export const useCatalog = (params: CatalogParams, enabled = true) =>
  useQuery({ queryKey: ["catalog", params], queryFn: () => apiGet("/api/v1/catalog/series", CatalogPageSchema, params), enabled, ...long });
export const useCatalogCommodities = (country?: string) =>
  useQuery({
    queryKey: ["catalog-commodities", country],
    queryFn: () => apiGet("/api/v1/catalog/commodities", z.array(CatalogCommoditySchema), { country }),
    ...long,
  });
export const useCatalogMarkets = (country?: string, commodity?: string) =>
  useQuery({
    queryKey: ["catalog-markets", country, commodity],
    queryFn: () => apiGet("/api/v1/catalog/markets", z.array(CatalogMarketSchema), { country, commodity }),
    enabled: !!country,
    ...long,
  });
export const useCoverageSummary = () =>
  useQuery({ queryKey: ["coverage-summary"], queryFn: () => apiGet("/api/v1/catalog/coverage", CoverageSummarySchema), ...long });
export const useMovers = (params: { country?: string; commodity?: string; limit?: number } = {}) =>
  useQuery({ queryKey: ["movers", params], queryFn: () => apiGet("/api/v1/movers", z.array(MoverSchema), params), ...long });

const one = (id?: string) => ({ enabled: !!id, retry: false, ...long });
export const useSeriesDetail = (id?: string) =>
  useQuery({ queryKey: ["series-detail", id], queryFn: () => apiGet(`/api/v1/series/${id}`, SeriesDetailSchema), ...one(id) });
export const useHistory = (id?: string) =>
  useQuery({ queryKey: ["history", id], queryFn: () => apiGet(`/api/v1/series/${id}/history`, HistorySchema), ...one(id) });
export const useMovement = (id?: string) =>
  useQuery({ queryKey: ["movement", id], queryFn: () => apiGet(`/api/v1/series/${id}/movement`, MovementSchema), ...one(id) });
export const useSeasonality = (id?: string) =>
  useQuery({ queryKey: ["seasonality", id], queryFn: () => apiGet(`/api/v1/series/${id}/seasonality`, SeasonalitySchema), ...one(id) });
export const useEnvironment = (id?: string) =>
  useQuery({ queryKey: ["environment", id], queryFn: () => apiGet(`/api/v1/series/${id}/environment`, EnvironmentSchema, { months: 120 }), ...one(id) });
export const useBrief = (id?: string) =>
  useQuery({ queryKey: ["brief", id], queryFn: () => apiGet(`/api/v1/series/${id}/brief`, BriefSchema), ...one(id) });

/** Query string for the comparison endpoint: `series_id` is repeated once per series. */
export function compareQuery(ids: string[], start?: string, end?: string, format?: "csv"): string {
  const q = new URLSearchParams();
  ids.forEach((i) => q.append("series_id", i));
  if (start) q.set("start", start);
  if (end) q.set("end", end);
  if (format) q.set("format", format);
  return q.toString();
}
export const compareUrl = (ids: string[], start?: string, end?: string, format?: "csv") =>
  `${apiUrl("/api/v1/compare")}?${compareQuery(ids, start, end, format)}`;

export const useCompare = (ids: string[], start?: string, end?: string) =>
  useQuery({
    queryKey: ["compare", ids, start, end],
    queryFn: () => apiGet(`/api/v1/compare?${compareQuery(ids, start, end)}`, CompareSchema),
    enabled: ids.length >= 2,
    retry: false,
    ...long,
  });

export const useStudy = (studyId: string, phase: "confirmatory" | "exploratory") =>
  useQuery({
    queryKey: ["study", studyId, phase],
    queryFn: () => apiGet(`/api/v1/studies/${studyId}`, StudySchema, { phase }),
    retry: false,
    ...long,
  });

export const historyCsvUrl = (id: string) => apiUrl(`/api/v1/series/${id}/history`, { format: "csv" });

export const MOVEMENT_LABEL: Record<string, { text: string; tone: "good" | "neutral" | "warn" | "muted" }> = {
  typical: { text: "Typical", tone: "neutral" },
  larger_than_usual: { text: "Larger than usual", tone: "neutral" },
  unusual: { text: "Unusual", tone: "warn" },
  exceptional: { text: "Exceptional", tone: "warn" },
  insufficient_history: { text: "Too little history", tone: "muted" },
};
