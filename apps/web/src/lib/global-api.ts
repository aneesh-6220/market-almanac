"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiGet, apiUrl } from "./api";
import { CatalogSeriesSchema, SummarySchema } from "./market-api";

/* The global price layer: every country with stored WFP prices, not only the ones with a forecast evaluation. */

const num = z.number().nullable();
const str = z.string().nullable();
const long = { staleTime: 5 * 60_000 };

export const TIER_ORDER = ["forecast_evaluated", "research_eligible", "validated", "ingested"] as const;
export type Tier = (typeof TIER_ORDER)[number];

/** Short, plain-language label per data tier. "Research eligible" and "forecast evaluated" are the only tiers that
 *  claim anything about forecastability; "validated" and "ingested" mean prices are stored and (for validated) checked. */
export const TIER_LABEL: Record<string, { text: string; tone: "good" | "neutral" | "warn" | "muted" }> = {
  forecast_evaluated: { text: "Forecast evaluated", tone: "good" },
  research_eligible: { text: "Research eligible", tone: "neutral" },
  validated: { text: "Prices validated", tone: "muted" },
  ingested: { text: "Prices ingested", tone: "muted" },
};

export const GlobalCountrySchema = z.object({
  country_iso3: z.string(),
  name: z.string(),
  markets: z.number(),
  commodities: z.number(),
  series: z.number(),
  usable_series: z.number(),
  eligible_series: z.number(),
  observations: z.number(),
  first_period: str,
  last_period: str,
  currencies: z.array(z.string()),
  price_types: z.array(z.string()),
  snapshot_id: z.string(),
  markets_with_coordinates: z.number(),
  market_coordinate_completeness: num,
  status: z.string(),
  status_note: str,
  research_eligible: z.boolean(),
  forecast_evaluated: z.boolean(),
  evaluations: z.number(),
});
export type GlobalCountry = z.infer<typeof GlobalCountrySchema>;

export const GlobalCountriesSchema = z.object({
  countries: z.array(GlobalCountrySchema),
  totals: z.record(z.string(), z.number()),
  status_definitions: z.record(z.string(), z.string()),
  layout: z.string(),
  synthetic: z.boolean(),
});

export const EvaluationRecordSchema = z
  .object({ id: z.string(), kind: z.string(), study: z.string().nullable().optional(), evidence_class: z.string().nullable().optional() })
  .loose();
export type EvaluationRecord = z.infer<typeof EvaluationRecordSchema>;

export const GlobalCountryDetailSchema = GlobalCountrySchema.extend({
  snapshot: z.object({
    snapshot_id: z.string(),
    layout: z.string().optional(),
    observation_hash: str.optional(),
    file_sha256: str.optional(),
    created_at: str.optional(),
    revision: str.optional(),
    parent_snapshot_id: str.optional(),
    diff: z.object({ added: z.number(), removed: z.number(), revised: z.number() }).nullable().optional(),
  }),
  evaluation_records: z.array(EvaluationRecordSchema),
  known_restrictions: z.array(z.string()),
  attribution: z.string(),
});
export type GlobalCountryDetail = z.infer<typeof GlobalCountryDetailSchema>;

export const GlobalMarketSchema = z.object({
  country_iso3: z.string(),
  market_code: z.string(),
  market_name: z.string(),
  admin1_name: str,
  admin2_name: str.optional(),
  lat: num,
  lon: num,
  coordinate_status: z.enum(["ok", "missing", "invalid"]),
  series: z.number(),
  usable_series: z.number(),
  commodities: z.number(),
  first_period: str,
  last_period: str,
  observations: z.number(),
});
export type GlobalMarket = z.infer<typeof GlobalMarketSchema>;
export const GlobalMarketsSchema = z.object({
  country_iso3: z.string(),
  items: z.array(GlobalMarketSchema),
  total: z.number(),
  markets_without_valid_coordinates: z.number(),
  snapshot_id: z.string(),
});

export const GlobalCommoditySchema = z.object({
  country_iso3: z.string(),
  commodity_code: z.string(),
  commodity_name: z.string(),
  commodity_category: str,
  markets: z.number(),
  series: z.number(),
  usable_series: z.number(),
  eligible_series: z.number(),
  units: z.array(z.string()),
  currencies: z.array(z.string()),
  price_types: z.array(z.string()),
  first_period: str,
  last_period: str,
  observations: z.number(),
});
export type GlobalCommodity = z.infer<typeof GlobalCommoditySchema>;
export const GlobalCommoditiesSchema = z.object({
  country_iso3: z.string(),
  items: z.array(GlobalCommoditySchema),
  total: z.number(),
  snapshot_id: z.string(),
});

export const GlobalSeriesSchema = CatalogSeriesSchema.extend({
  admin2_name: str.optional(),
  snapshot_id: z.string(),
  months_spanned: z.number(),
  missing_months: z.number(),
  n_conflicting_duplicates: z.number(),
  coordinate_status: z.enum(["ok", "missing", "invalid"]),
});
export type GlobalSeries = z.infer<typeof GlobalSeriesSchema>;
export const GlobalSeriesPageSchema = z.object({
  items: z.array(GlobalSeriesSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  snapshot_id: str.optional(),
  country_iso3: z.string(),
});

export const GlobalDetailSchema = z.object({
  series: GlobalSeriesSchema,
  summary: SummarySchema,
  completeness: z.object({
    months_spanned: z.number(),
    valid_months: z.number(),
    missing_months: z.number(),
    coverage: z.number(),
    longest_gap_months: z.number(),
    records_stored: z.number(),
    records_not_valid: z.number(),
    months_with_duplicate_records: z.number(),
    quality_flag_counts: z.record(z.string(), z.number()),
    usable: z.boolean(),
    eligible: z.boolean(),
    ineligible_reasons: str,
  }),
  provenance: z.object({
    provider: z.string(),
    snapshot_id: z.string(),
    snapshot_created_at: str.optional(),
    snapshot_revision: str.optional(),
    observation_hash: str.optional(),
    file_sha256: str.optional(),
    source_refs: z.array(z.string()),
    retrieved_at: str,
    attribution: z.string(),
    license_note: z.string(),
    observation_basis: z.string(),
  }),
  country: z.object({
    country_iso3: z.string(),
    name: z.string(),
    status: z.string(),
    status_note: str,
    forecast_evaluated: z.boolean(),
    evaluation_records: z.array(EvaluationRecordSchema),
  }),
});
export type GlobalDetail = z.infer<typeof GlobalDetailSchema>;

export const ObservationSchema = z.object({
  period: z.string(),
  price: num,
  price_flag: str,
  quality_flags: z.array(z.string()),
  valid: z.boolean(),
  used_in_series: z.boolean(),
  duplicate_month: z.boolean(),
  reference_period_start: str,
  reference_period_end: str,
  source_ref: str,
  retrieved_at: str,
});
export type Observation = z.infer<typeof ObservationSchema>;
export const ObservationPageSchema = z.object({
  series_id: z.string(),
  currency: z.string(),
  unit: z.string(),
  price_type: z.string(),
  items: z.array(ObservationSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  start: str,
  end: str,
  snapshot_id: z.string(),
  observation_basis: z.string(),
});

/* ---- hooks ---- */

export const useGlobalCountries = () =>
  useQuery({ queryKey: ["global-countries"], queryFn: () => apiGet("/api/v1/global/countries", GlobalCountriesSchema), ...long });
export const useGlobalCountry = (iso3?: string) =>
  useQuery({
    queryKey: ["global-country", iso3],
    queryFn: () => apiGet(`/api/v1/global/countries/${iso3}`, GlobalCountryDetailSchema),
    enabled: !!iso3,
    ...long,
  });
export const useGlobalMarkets = (iso3?: string, commodity?: string) =>
  useQuery({
    queryKey: ["global-markets", iso3, commodity],
    queryFn: () => apiGet(`/api/v1/global/countries/${iso3}/markets`, GlobalMarketsSchema, { commodity }),
    enabled: !!iso3,
    placeholderData: keepPreviousData,
    ...long,
  });
export const useGlobalCommodities = (iso3?: string, market?: string) =>
  useQuery({
    queryKey: ["global-commodities", iso3, market],
    queryFn: () => apiGet(`/api/v1/global/countries/${iso3}/commodities`, GlobalCommoditiesSchema, { market }),
    enabled: !!iso3,
    placeholderData: keepPreviousData,
    ...long,
  });

export type GlobalSeriesParams = {
  commodity?: string;
  market?: string;
  unit?: string;
  currency?: string;
  price_type?: string;
  q?: string;
  usable_only?: boolean;
  eligible_only?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
};
export const useGlobalSeries = (iso3: string | undefined, params: GlobalSeriesParams) =>
  useQuery({
    queryKey: ["global-series", iso3, params],
    queryFn: () => apiGet(`/api/v1/global/countries/${iso3}/series`, GlobalSeriesPageSchema, params),
    enabled: !!iso3,
    placeholderData: keepPreviousData,
    ...long,
  });

const one = (id?: string, when = true) => ({ enabled: !!id && when, ...long });
export const useGlobalDetail = (id?: string) =>
  useQuery({ queryKey: ["global-detail", id], queryFn: () => apiGet(`/api/v1/global/series/${id}`, GlobalDetailSchema), ...one(id) });
export const useObservations = (
  id: string | undefined,
  params: { limit: number; offset: number; start?: string; end?: string },
  when = true,
) =>
  useQuery({
    queryKey: ["global-observations", id, params],
    queryFn: () => apiGet(`/api/v1/global/series/${id}/observations`, ObservationPageSchema, params),
    placeholderData: keepPreviousData,
    ...one(id, when),
  });

/** Download URL for the stored observations of one series (every record, flags included). */
export const exportUrl = (id: string, format: "csv" | "json", start?: string, end?: string) =>
  apiUrl(`/api/v1/global/series/${id}/export`, { format, start, end });

/** Series that measure the same thing as `s` in other markets of the same country: same commodity, unit, price type
 *  and currency, the only ones whose prices may be set side by side. */
export const comparableQuery = (s: Pick<GlobalSeries, "commodity_code" | "unit" | "price_type" | "currency">): GlobalSeriesParams => ({
  commodity: s.commodity_code,
  unit: s.unit,
  price_type: s.price_type,
  currency: s.currency,
  sort: "observations",
  limit: 50,
});

/** Mixed-measurement check shared by the explorer and the comparison page. */
export function incompatibility(rows: Pick<GlobalSeries, "commodity_code" | "unit" | "price_type" | "currency">[]): string | null {
  if (rows.length < 2) return null;
  const d = (k: "commodity_code" | "unit" | "price_type" | "currency") => new Set(rows.map((r) => r[k])).size > 1;
  if (d("commodity_code")) return "different commodities";
  if (d("unit")) return "different reporting units";
  if (d("price_type")) return "different price types";
  if (d("currency")) return "different currencies (only indexed comparison is possible; no conversion is applied)";
  return null;
}
