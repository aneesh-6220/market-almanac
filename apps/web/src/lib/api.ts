import { z } from "zod";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
/** A local API means a developer is running the stack, so errors may carry setup hints. */
export const LOCAL_API = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(API_URL);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

export function apiUrl(path: string, params?: Params): string {
  const u = new URL(API_URL + path);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, String(v));
  }
  return u.toString();
}

export async function apiGet<S extends z.ZodTypeAny>(path: string, schema: S, params?: Params): Promise<z.output<S>> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path, params), { headers: { accept: "application/json" } });
  } catch {
    throw new ApiError(
      0,
      LOCAL_API
        ? `Cannot reach the ShockTrace API at ${API_URL}. Start it with \`make api\`.`
        : "The ShockTrace data service is temporarily unavailable. Please try again in a few minutes.",
    );
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail);
  }
  const json = await res.json();
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError(500, `Unexpected response shape from ${path}: ${parsed.error.issues[0]?.message}`);
  }
  return parsed.data as z.output<S>;
}

const num = z.number().nullable();
const str = z.string().nullable();
const anyRecord = z.record(z.string(), z.any());

export const SnapshotSchema = z.object({
  snapshot_id: z.string(),
  dataset: z.string(),
  created_at: z.string(),
  row_count: z.number(),
  providers: z.array(z.string()),
  retrieved_at_min: str,
  retrieved_at_max: str,
  synthetic: z.boolean(),
  content_hash: z.string(),
});

export const StatusSchema = z.object({
  mode: z.string(),
  synthetic: z.boolean(),
  version: z.string(),
  snapshots: z.array(SnapshotSchema),
  counts: z.record(z.string(), z.number()),
  latest_quality_report: anyRecord.nullable(),
  sources: z.array(anyRecord),
  notices: z.array(z.string()),
});
export type Status = z.infer<typeof StatusSchema>;

export const SourceSchema = z.object({
  provider_id: z.string(),
  name: z.string(),
  description: z.string(),
  homepage: z.string(),
  docs_url: z.string(),
  license: z.string(),
  attribution: z.string(),
  auth_kind: z.string(),
  configured: z.boolean(),
  health_status: z.string(),
  health_message: str,
  health_checked_at: str,
  health_latency_ms: num,
  last_live_success_at: str,
  last_retrieval_at: str,
  verification: z.string(),
  datasets: z.array(anyRecord),
  caveats: z.array(z.string()),
  capabilities: z.array(z.string()),
});
export type Source = z.infer<typeof SourceSchema>;

export const CountrySchema = z.object({
  iso3: z.string(),
  name: z.string(),
  region: str,
  income_level: str,
  provider: z.string(),
  n_markets: z.number(),
});
export const CommoditySchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  category: str,
  provider: z.string(),
  fao_item_code: str,
});
export const MarketSchema = z.object({
  id: z.string(),
  provider: z.string(),
  country_iso3: z.string(),
  market_code: z.string(),
  name: z.string(),
  admin1: str,
  admin2: str,
  lat: num,
  lon: num,
  weather_location_id: str,
  n_series: z.number(),
  first_period: str,
  last_period: str,
  eligible_series: z.number(),
});
export type Market = z.infer<typeof MarketSchema>;

export const SeriesSchema = z.object({
  series_id: z.string(),
  country_iso3: z.string(),
  market_code: str.optional(),
  market_name: z.string(),
  commodity_code: str.optional(),
  commodity_name: z.string(),
  unit: z.string(),
  price_type: z.string(),
  currency: z.string(),
  price_flag: z.string(),
  first_period: str,
  last_period: str,
  n_observations: z.number(),
  coverage: z.number(),
  longest_gap_months: z.number(),
  eligible: z.boolean(),
  reasons: z.array(z.string()),
  extreme_change_classes: z.record(z.string(), z.number()),
  has_coordinates: z.boolean(),
});
export type Series = z.infer<typeof SeriesSchema>;

const page = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number(),
    limit: z.number(),
    offset: z.number(),
    snapshot_id: str.optional(),
    synthetic: z.boolean(),
  });

export const PricePageSchema = page(
  z.object({
    series_id: z.string(),
    period: z.string(),
    price: num,
    unit: z.string(),
    currency: z.string(),
    price_type: z.string(),
    market_name: z.string(),
    commodity_name: z.string(),
    quality_flags: str,
    source_ref: str,
    retrieved_at: str,
  }),
);
export type PricePage = z.infer<typeof PricePageSchema>;

export const WeatherSchema = z.object({
  location_id: z.string(),
  lat: num,
  lon: num,
  spatial_basis: z.string(),
  proxy_warning: z.string(),
  climatology: z.string(),
  units: z.record(z.string(), z.string()),
  snapshot_id: str,
  synthetic: z.boolean(),
  items: z.array(
    z.object({
      location_id: z.string(),
      period: z.string(),
      precip_total_mm: num,
      t2m_mean_c: num,
      t2m_max_mean_c: num,
      t2m_min_mean_c: num,
      heat_days_t2m_max_ge_35c: num,
      complete: z.boolean().nullable(),
      rain_anomaly_z: num,
      temp_anomaly_z: num,
    }),
  ),
});
export type Weather = z.infer<typeof WeatherSchema>;

export const IndicatorPageSchema = page(
  z.object({
    provider: z.string(),
    country_iso3: z.string(),
    indicator_code: z.string(),
    indicator_name: z.string(),
    frequency: z.string(),
    period: z.string(),
    value: num,
    unit: str,
    source_ref: str,
  }),
);
export const AgriPageSchema = page(
  z.object({
    provider: z.string(),
    country_iso3: z.string(),
    item_code: z.string(),
    item_name: z.string(),
    element_code: z.string(),
    element_name: z.string(),
    unit: z.string(),
    year: z.number(),
    value: num,
    flag: str,
  }),
);

export const LagSchema = z.object({
  series_id: z.string(),
  weather_variable: z.string(),
  target: z.string(),
  items: z.array(z.object({ lag_months: z.number(), correlation: num, n: z.number() })),
  caveat: z.string(),
});

export const ExperimentSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  mode: z.string(),
  created_at: z.string(),
  status: z.string(),
  synthetic: z.boolean(),
  country_iso3: z.string(),
  commodity_codes: z.array(z.string()),
  verdict: str,
  statement: str,
  n_series: z.number(),
  config_hash: z.string(),
  evidence_class: z.string().optional(),
  study: str.optional(),
  variant: z.string().optional(),
  method_revision: str.optional(),
  price_release_lag_months: z.number().optional(),
  superseded_by: str.optional(),
  superseded_reason: str.optional(),
  current: z.boolean().optional(),
});
export type ExperimentSummary = z.infer<typeof ExperimentSummarySchema>;

/* Experiment results are large nested JSON documents produced by the research engine.
   The shapes below cover the fields the interface reads; extra fields are ignored. */
const Bootstrap = z.object({ ratio: num, ci_low: num, ci_high: num }).passthrough();
export const ComparisonSchema = z
  .object({
    role: z.string(),
    task: z.string(),
    horizon: z.number(),
    model_a: z.string(),
    model_b: z.string(),
    relative_loss_b_vs_a: num,
    mean_loss_a: z.number(),
    mean_loss_b: z.number(),
    n_rows: z.number(),
    positives: num.optional(),
    dm: z.object({ stat: num, p_value_two_sided: num, p_value_b_better: num, n_periods: z.number(), lags: z.number() }).passthrough(),
    bootstrap_loss_ratio: Bootstrap,
    influence: z.object({ fragile: z.boolean().optional(), reasons: z.array(z.string()).optional() }).passthrough().nullable().optional(),
    subperiods: z.array(z.object({ period: z.string(), start: z.string(), mean_diff: num, n: z.number() })),
    verdict: z.string(),
    reason: z.string(),
  })
  .passthrough();
export type Comparison = z.infer<typeof ComparisonSchema>;

export const TaskSchema = z
  .object({
    task: z.string(),
    horizon: z.number(),
    target: z.string().optional(),
    threshold: num.optional(),
    status: z.string().optional(),
    reason: z.string().optional(),
    test_period: z.array(z.string()).optional(),
    n_test_rows: z.number().optional(),
    n_test_periods: z.number().optional(),
    n_series: z.number().optional(),
    folds: z.array(anyRecord).optional(),
    models: z.record(z.string(), anyRecord).optional(),
    comparisons: z.array(ComparisonSchema).default([]),
    residual_diagnostics: anyRecord.optional(),
    permutation_importance: z.record(z.string(), z.array(anyRecord)).optional(),
  })
  .passthrough();
export type Task = z.infer<typeof TaskSchema>;

export const ResultsSchema = z
  .object({
    experiment_id: z.string(),
    name: z.string(),
    mode: z.string(),
    synthetic: z.boolean(),
    created_at: z.string(),
    status: z.string(),
    config: anyRecord,
    config_hash: z.string(),
    manifest: anyRecord,
    tasks: z.array(TaskSchema),
    sensitivity: z.array(anyRecord).default([]),
    forecasts: z.array(anyRecord).default([]),
    conclusion: anyRecord,
    limitations: z.array(z.string()).default([]),
    warnings: z.array(z.string()).default([]),
    data: anyRecord.optional(),
    series_quality: z.array(anyRecord).default([]),
    families_used: z.array(z.string()).optional(),
    feature_availability: anyRecord.optional(),
  })
  .passthrough();
export type Results = z.infer<typeof ResultsSchema>;

export const ExperimentDetailSchema = z.object({ summary: ExperimentSummarySchema, results: ResultsSchema });

export const ForecastSchema = z.object({
  id: z.string(),
  experiment_id: z.string(),
  series_id: z.string(),
  task: z.string(),
  horizon: z.number(),
  model: z.string(),
  origin_period: z.string(),
  target_period: z.string(),
  information_cutoff: z.string(),
  status: z.string(),
  validation_status: z.string(),
  reason: str,
  payload: anyRecord,
  synthetic: z.boolean(),
});
export type Forecast = z.infer<typeof ForecastSchema>;

export const PredictionPageSchema = page(
  z.object({
    series_id: z.string(),
    origin: z.string(),
    target_period: z.string(),
    model: z.string(),
    y: num,
    pred: num,
    fold: z.number(),
  }),
);

export const QualitySchema = z
  .object({
    id: z.string(),
    created_at: z.string(),
    summary: anyRecord,
    consistency_issues: z.array(z.string()).default([]),
    series: z.array(SeriesSchema.passthrough()).default([]),
    extremes: z.array(anyRecord).default([]),
    weather: anyRecord.optional(),
    macro: anyRecord.optional(),
    agriculture: anyRecord.optional(),
    snapshots: anyRecord.optional(),
    synthetic: z.boolean().optional(),
    series_total: z.number().optional(),
    extremes_total: z.number().optional(),
    consistency_issues_total: z.number().optional(),
  })
  .passthrough();

export const JobSchema = z.object({
  id: z.string(),
  provider_id: z.string(),
  dataset: z.string(),
  status: z.string(),
  started_at: z.string(),
  finished_at: str,
  rows: num,
  snapshot_id: str,
  requests_made: num,
  warnings: z.array(z.string()),
  error: str,
  params: anyRecord,
});

export const CoverageSchema = z.object({
  months: z.array(z.string()),
  series: z.array(
    z.object({
      series_id: z.string(),
      market_name: z.string(),
      commodity_name: z.string(),
      unit: z.string(),
      observed: z.array(z.number()),
    }),
  ),
  snapshot_id: str,
});
