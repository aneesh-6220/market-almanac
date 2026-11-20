import { z } from "zod";

/* The `context.economic` section of an investigation (schema docs/schemas/economic-context-1.schema.json).
   Missing values arrive as null with a stated reason; nothing here turns a missing value into zero. */

const num = z.number().nullable();
const str = z.string().nullable();

const Coverage = z.object({
  first_period: str.optional(),
  last_period: str.optional(),
  n_obs: z.number(),
  months_in_window: z.number(),
  months_observed_in_window: z.number(),
  months_missing_in_window: z.number(),
  stale: z.boolean().optional(),
  ends_before_event: z.boolean().optional(),
  release_lag_months: z.number().optional(),
});

const Change = {
  yoy_pct: num.optional(),
  yoy_unavailable_reason: str.optional(),
  baseline_to_peak_pct: num.optional(),
  baseline_to_peak_unavailable_reason: str.optional(),
  chart_index: z.array(num).optional(),
};

export const Indicator = z.object({
  series_key: z.string(),
  label: z.string(),
  unit: z.string(),
  state: z.string(),
  reason: str.optional(),
  source_ref: str.optional(),
  coverage: Coverage.nullable().optional(),
  level_at_event: num.optional(),
  mom_pct: num.optional(),
  ...Change,
});
export type Indicator = z.infer<typeof Indicator>;

const Benchmark = Indicator.extend({
  benchmark_id: z.string().optional(),
  summary: z.string().optional(),
  definition: z.object({ text: z.string().optional(), sources: z.string().optional() }).optional(),
  local_currency: z
    .object({
      ...Change,
      decomposition_yoy: z
        .object({ usd_benchmark_log: z.number(), exchange_rate_log: z.number(), local_currency_log: z.number(), local_currency_change: z.number() })
        .nullable()
        .optional(),
    })
    .nullable()
    .optional(),
});
export type Benchmark = z.infer<typeof Benchmark>;

export const UNAVAILABLE_STATES = ["demo_mode", "not_installed", "metadata_only"] as const;

export const EconomicUnavailable = z.object({
  status: z.enum(UNAVAILABLE_STATES),
  reason: z.string(),
});

export const EconomicAvailable = z.object({
  format: z.string(),
  status: z.enum(["ok", "no_context"]),
  context_id: z.string(),
  snapshot: z.object({ snapshot_id: z.string(), observation_hash: z.string(), vintage: z.string(), created_at: z.string().optional() }),
  as_of: str,
  assumptions: z.object({ release_lags_months: z.record(z.string(), z.number()), note: z.string() }),
  window: z.object({
    start: z.string(),
    end: z.string(),
    event: z.string(),
    onset: str.optional(),
    peak: str.optional(),
    baseline_start: z.string(),
    baseline_end: z.string(),
  }),
  inflation: z.object({ headline: Indicator, food: Indicator, food_minus_headline_yoy_pp: num.optional() }),
  exchange_rate: z.object({
    quote: z.string(),
    price_currency: z.string(),
    applicability: z.string(),
    currency_verified: z.boolean().optional(),
    regime: z.array(z.object({ id: z.string(), kind: z.string(), currency_name: z.string().optional(), interpretation: z.string().optional() })).nullable().optional(),
    period_average: Indicator,
    end_period: Indicator,
    average_vs_end_period_yoy_pp: num.optional(),
  }),
  price: z.object({ currency: z.string(), ...Change }),
  usd_price: z.object({ ...Change, note: z.string().optional() }).nullable().optional(),
  relative_changes: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      horizon: z.string(),
      status: z.string(),
      nominal_pct: num.optional(),
      deflator_pct: num.optional(),
      relative_pct: num.optional(),
      reason: str.optional(),
    }),
  ),
  international: z.object({
    status: z.string(),
    commodity: z.string().optional(),
    confidence: z.string().optional(),
    role: z.string().optional(),
    confidence_text: z.string().optional(),
    limitations: z.array(z.string()).optional(),
    unit_note: z.string().optional(),
    reason: z.string().optional(),
    items: z.array(Benchmark),
  }),
  lags: z.object({
    method: z.string(),
    lags_months: z.array(z.number()),
    through: z.string().optional(),
    caution: z.string(),
    pairs: z.array(
      z.object({
        key: z.string(),
        label: z.string(),
        n_pairs_lag0: z.number().optional(),
        rows: z.array(z.object({ lag: z.number(), n: z.number(), spearman: num.optional(), status: z.string() })),
      }),
    ),
  }),
  charts: z.object({ months: z.array(z.string()), event: z.string(), unit: z.string(), baseline: z.object({ start: z.string(), end: z.string() }) }),
  missing: z.array(z.object({ key: z.string(), label: z.string(), state: z.string(), reason: z.string() })),
  warnings: z.array(z.object({ code: z.string(), severity: z.string(), text: z.string() })),
  lineage: z.array(
    z.object({
      series_key: z.string(),
      provider: z.string(),
      dataset: z.string().optional(),
      label: z.string(),
      source_ref: z.string(),
      first_period: str.optional(),
      last_period: str.optional(),
      vintage_publication_date: str.optional(),
      retrieved_at: str.optional(),
      response_sha256: z.string(),
      observations_sha256: str.optional(),
      licence: z.string(),
      attribution: z.string(),
    }),
  ),
  transformations: z.record(z.string(), z.string()),
});
export type EconomicAvailable = z.infer<typeof EconomicAvailable>;

export const EconomicSection = z.union([EconomicAvailable, EconomicUnavailable]);
export type EconomicSection = z.infer<typeof EconomicSection>;

export const isAvailable = (e: EconomicSection): e is EconomicAvailable => e.status === "ok" || e.status === "no_context";

const Statement = z.object({ text: z.string(), inference: z.string(), keys: z.array(z.string()).optional() });

/** The deterministic evidence built from the section: propositions are set beside the figures, never asserted. */
export const EconomicEvidence = z.object({
  context_id: z.string(),
  observed: z.array(Statement),
  quantitative: z.array(Statement),
  consistent: z.array(Statement),
  unresolved: z.array(Statement),
  causal: z.array(Statement),
  gaps: z.array(z.string()),
  propositions: z.array(z.object({ proposition: z.string(), status: z.string(), verdict: z.string(), basis: z.string() })),
});
export type EconomicEvidence = z.infer<typeof EconomicEvidence>;

export const STATE_LABEL: Record<string, string> = {
  ok: "available",
  empty_series: "published but empty",
  no_series: "no series for this country",
  insufficient_history: "too short",
  not_applicable: "not applicable",
};

export const stateLabel = (s: string): string => STATE_LABEL[s] ?? s.replaceAll("_", " ");

export const UNAVAILABLE_TITLE: Record<string, string> = {
  demo_mode: "Economic context is not part of the synthetic demo",
  not_installed: "Economic context is not installed on this deployment",
  metadata_only: "This deployment holds the economic-context sources but not the observations",
};

export type ChartLine = { name: string; data: (number | null)[]; role: "price" | "reference" | "reference2" | "usd" };

/** Months in the window at which a series has no value: shown as gaps, never joined across. */
export const missingMonths = (d: (number | null)[] | undefined): number => (d ? d.filter((v) => v == null).length : 0);
