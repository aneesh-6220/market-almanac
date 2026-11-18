"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { API_URL, ApiError, apiGet } from "./api";

/* Global coverage registry, market index, research workbench and published studies. */

const num = z.number().nullable();
const str = z.string().nullable();
const long = { staleTime: 10 * 60_000 };

export const STATUS_ORDER = [
  "forecast_evaluated",
  "research_eligible",
  "validated",
  "ingested",
  "temporarily_unavailable",
  "discoverable",
  "unsupported",
] as const;
export type CoverageStatus = (typeof STATUS_ORDER)[number];

/** Okabe–Ito colours: distinguishable with the common colour-vision deficiencies. Text labels always accompany them. */
export const STATUS_STYLE: Record<CoverageStatus, { label: string; color: string }> = {
  forecast_evaluated: { label: "Forecast-evaluated", color: "#0072B2" },
  research_eligible: { label: "Research-eligible", color: "#009E73" },
  validated: { label: "Validated", color: "#E69F00" },
  ingested: { label: "Ingested", color: "#CC79A7" },
  temporarily_unavailable: { label: "Temporarily unavailable", color: "#D55E00" },
  discoverable: { label: "Discoverable", color: "#999999" },
  unsupported: { label: "No integrated source", color: "#BBBBBB" },
};

export const RegistryRowSchema = z.object({
  country_iso3: z.string(),
  name: z.string(),
  status: z.enum(STATUS_ORDER),
  price_sources: z.array(z.string()),
  markets: num.optional(),
  commodities: num.optional(),
  series: num.optional(),
  observations: num.optional(),
  first_period: str.optional(),
  last_period: str.optional(),
  eligible_series: num.optional(),
  market_coordinate_completeness: num.optional(),
  forecast_eligible: z.boolean(),
  macro_ingested: z.boolean(),
  agriculture_ingested: z.boolean(),
  last_successful_refresh: str.optional(),
});
export type RegistryRow = z.infer<typeof RegistryRowSchema>;

export const RegistrySchema = z.object({
  registry_version: z.string(),
  generated_at: z.string(),
  source: z.string(),
  status_definitions: z.record(z.string(), z.string()),
  counts: z.record(z.string(), z.number()),
  totals: z.object({
    countries_listed: z.number(),
    countries_with_observations: z.number(),
    observations: z.number(),
    series: z.number(),
    markets: z.number(),
    eligible_series: z.number(),
  }),
  discovery: z.object({ provider: str, retrieved_at: str, countries: z.number() }),
  countries: z.array(RegistryRowSchema),
});
export type Registry = z.infer<typeof RegistrySchema>;

export const CountryRecordSchema = RegistryRowSchema.extend({
  qc: z.record(z.string(), z.any()).nullable(),
  environment: z.record(z.string(), z.any()),
  evaluations: z.array(z.record(z.string(), z.any())),
  snapshot: z.record(z.string(), z.any()).nullable(),
  licence: str,
  known_restrictions: z.array(z.string()),
  eligible_by_commodity: z.array(z.record(z.string(), z.any())),
  currencies: z.array(z.string()).nullable().optional(),
  price_types: z.array(z.string()).nullable().optional(),
  hapi_updated: str.optional(),
  last_attempt: z.record(z.string(), z.any()).nullable(),
});
export type CountryRecord = z.infer<typeof CountryRecordSchema>;

export const MarketIndexSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.tuple([z.string(), z.string(), z.string(), z.number(), z.number(), z.number(), z.string()])),
  source: z.string(),
});
export type MarketIndex = z.infer<typeof MarketIndexSchema>;

export const useRegistry = () =>
  useQuery({ queryKey: ["registry"], queryFn: () => apiGet("/api/v1/coverage/registry", RegistrySchema), ...long });
export const useCountryRecord = (iso3?: string) =>
  useQuery({
    queryKey: ["registry", iso3],
    queryFn: () => apiGet(`/api/v1/coverage/registry/${iso3}`, CountryRecordSchema),
    enabled: !!iso3 && /^[A-Z]{3}$/.test(iso3),
    ...long,
  });
export const useMarketIndex = () =>
  useQuery({ queryKey: ["market-index"], queryFn: () => apiGet("/api/v1/coverage/markets", MarketIndexSchema), ...long });

// ---------------------------------------------------------------- studies

export const StudyListItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  study_type: z.string(),
  evidence_class: z.string(),
  question: z.string(),
  headline: z.string(),
  published_at: z.string(),
  spec_hash: z.string(),
  frozen: z.boolean().nullable(),
  n_countries: num,
});
export type StudyListItem = z.infer<typeof StudyListItemSchema>;

const CI = z.object({ ci_low: num.optional(), ci_high: num.optional(), reps: num.optional(), method: z.string().optional() }).nullable();

export const PooledResultSchema = z
  .object({
    status: z.string().optional(),
    loss_ratio: num.optional(),
    pct_change_in_loss: num.optional(),
    n_months: num.optional(),
    n_countries: num.optional(),
    n_series: num.optional(),
    n_forecasts: num.optional(),
    first_origin: str.optional(),
    last_origin: str.optional(),
    dm_stat: num.optional(),
    p_challenger_better: num.optional(),
    p_challenger_worse: num.optional(),
    p_two_sided: num.optional(),
    ci_primary: CI.optional(),
    ci_block: CI.optional(),
    sign_test_countries: z.record(z.string(), z.any()).optional(),
    influence: z.record(z.string(), z.any()).optional(),
    leave_one_country_out: z.record(z.string(), z.any()).nullable().optional(),
    per_country: z.array(z.record(z.string(), z.any())).optional(),
  })
  .passthrough();
export type PooledResult = z.infer<typeof PooledResultSchema>;

export const StudySchema = z
  .object({
    id: z.string(),
    title: z.string(),
    study_type: z.string(),
    evidence_class: z.string(),
    question: z.string(),
    hypothesis: z.string(),
    estimand: z.string(),
    spec_hash: z.string(),
    spec: z.record(z.string(), z.any()),
    families: z.record(z.string(), z.string()).nullable(),
    headline: z.string(),
    published_at: z.string(),
    frozen: z.boolean(),
    freeze: z.record(z.string(), z.any()).nullable(),
    n_countries: num,
    results: z.record(z.string(), z.any()),
  })
  .passthrough();
export type Study = z.infer<typeof StudySchema>;

export const useStudies = () =>
  useQuery({ queryKey: ["wb-studies"], queryFn: () => apiGet("/api/v1/workbench/studies", z.array(StudyListItemSchema)), ...long });
export const useStudy = (id?: string) =>
  useQuery({
    queryKey: ["wb-study", id],
    queryFn: () => apiGet(`/api/v1/workbench/studies/${id}`, StudySchema),
    enabled: !!id,
    ...long,
  });

// ---------------------------------------------------------------- validation

export const ValidationSchema = z.object({
  valid: z.boolean(),
  problems: z.array(z.string()),
  spec_hash: z.string().optional(),
  id: z.string().optional(),
  study_type: z.string().optional(),
  evidence_class: z.string().optional(),
  countries: z.array(z.string()).optional(),
  run_locally: z.array(z.string()).optional(),
});
export type Validation = z.infer<typeof ValidationSchema>;

/** Validate a specification on the server (parsing and scientific checks only; nothing is executed). */
export async function validateSpec(text: string): Promise<Validation> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1/workbench/validate`, {
      method: "POST",
      headers: { "content-type": "text/plain", accept: "application/json" },
      body: text,
    });
  } catch {
    throw new ApiError(0, "The validation service is unreachable; check the specification locally with `market-almanac research validate`.");
  }
  if (!res.ok) throw new ApiError(res.status, res.status === 413 ? "Specification too large (64 KB limit)." : res.statusText);
  const parsed = ValidationSchema.safeParse(await res.json());
  if (!parsed.success) throw new ApiError(500, "Unexpected validation response");
  return parsed.data;
}
