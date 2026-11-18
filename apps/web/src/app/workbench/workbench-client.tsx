"use client";

import { useMemo, useState } from "react";

import {
  ErrorState,
  Field,
  inputClass,
  Loading,
  Note,
  Panel,
  Stat,
  Tag,
} from "@/components/ui";
import { download } from "@/lib/format";
import {
  type RegistryRow,
  useRegistry,
  type Validation,
  validateSpec,
} from "@/lib/research-api";

type StudyType = "predictive" | "descriptive" | "associational";
const ROBUSTNESS = [
  "price_lag_0",
  "price_lag_2",
  "weather_lag_1",
  "raw_precipitation",
  "leave_one_country_out",
  "drop_top3_months",
];
const CONTROLS = ["weather_time_shift_60", "weather_permuted_cells"];
const FAMILIES: Record<string, string> = {
  A: "price history",
  B: "price history + market-local weather",
};

const q = (s: string) => JSON.stringify(s); // a JSON string is a valid YAML double-quoted scalar
const list = (xs: (string | number)[]) => `[${xs.join(", ")}]`;

export interface Draft {
  id: string;
  title: string;
  question: string;
  hypothesis: string;
  estimand: string;
  studyType: StudyType;
  confirmatory: boolean;
  countries: string[];
  categories: string;
  horizons: number[];
  testStart: string;
  robustness: string[];
  controls: string[];
  seed: number;
}

/** Turn the form into a specification document (pure; tested). */
export function toYaml(d: Draft): string {
  const L: string[] = [
    "spec_version: ma-research-spec/1",
    `id: ${d.id}`,
    `title: ${q(d.title)}`,
    `question: ${q(d.question)}`,
    `hypothesis: ${q(d.hypothesis)}`,
    `estimand: ${q(d.estimand)}`,
    `study_type: ${d.studyType}`,
    `evidence_class: ${d.confirmatory ? "confirmatory" : "exploratory"}`,
    "population:",
    `  countries: ${list(d.countries)}`,
    "  price_types: [Retail]",
  ];
  const cats = d.categories
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  if (cats.length) L.push(`  commodity_categories: ${list(cats.map(q))}`);
  L.push(
    "timing:",
    "  price_release_lag_months: 1",
    "  weather_release_lag_months: 0",
  );
  if (d.studyType === "predictive") {
    L.push(
      "predictive:",
      `  horizons: ${list(d.horizons)}`,
      "  families: [A, B]",
      "  evaluation: rolling_origin",
    );
    if (d.testStart) L.push(`  test_start: ${d.testStart}`);
    L.push("  hypotheses:");
    d.horizons.forEach((h, i) =>
      L.push(
        `    - id: H${i + 1}`,
        `      statement: ${q(`Family B has lower ${h}-month forecast loss than family A.`)}`,
        "      challenger: B",
        "      baseline: A",
        `      horizon: ${h}`,
      ),
    );
    // the server rejects a country bootstrap with fewer than five countries
    L.push(
      "inference:",
      "  multiplicity: holm",
      `  bootstrap: ${d.countries.length >= 5 ? "two_way_country_month" : "moving_block_months"}`,
    );
  } else if (d.studyType === "associational") {
    L.push(
      "associational:",
      "  exposure: rain_anom",
      "  exposure_lags: [1, 2, 3]",
      "inference:",
      "  bootstrap: none",
    );
  } else {
    L.push(
      "descriptive:",
      "  statistics: [trend, seasonality, volatility, dispersion, comovement]",
      "inference:",
      "  bootstrap: none",
    );
  }
  if (d.studyType !== "descriptive") {
    if (d.robustness.length) L.push(`robustness: ${list(d.robustness)}`);
    if (d.controls.length && d.studyType === "predictive")
      L.push(`negative_controls: ${list(d.controls)}`);
  }
  L.push(
    `seed: ${d.seed}`,
    "limitations:",
    `  - ${q("Predictive or associational evidence only; not causal.")}`,
  );
  return L.join("\n") + "\n";
}

function Check({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-ink-3">{hint}</span>}
      </span>
    </label>
  );
}

function Preview({ rows, picked }: { rows: RegistryRow[]; picked: string[] }) {
  const sel = rows.filter((r) => picked.includes(r.country_iso3));
  const sum = (k: "eligible_series" | "observations" | "markets") =>
    sel.reduce((a, r) => a + (r[k] ?? 0), 0);
  const noWeather = sel.filter(
    (r) =>
      r.status !== "research_eligible" && r.status !== "forecast_evaluated",
  );
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Countries" value={sel.length} />
        <Stat label="Markets" value={sum("markets").toLocaleString("en")} />
        <Stat
          label="Eligible series"
          value={sum("eligible_series").toLocaleString("en")}
          hint="all commodities, before filters"
        />
        <Stat
          label="Observations"
          value={sum("observations").toLocaleString("en")}
        />
      </div>
      {noWeather.length > 0 && (
        <Note tone="warn">
          {noWeather.map((r) => r.country_iso3).join(", ")}{" "}
          {noWeather.length === 1 ? "is" : "are"} not research-eligible (too few
          eligible series or no stored weather); a predictive run would drop{" "}
          {noWeather.length === 1 ? "it" : "them"}.
        </Note>
      )}
      <p className="text-xs text-ink-3">
        Counts come from the coverage registry metadata. The exact analysis
        population (groups and series) is computed by{" "}
        <code>research preview</code> on the stored data.
      </p>
    </div>
  );
}

export function WorkbenchClient() {
  const reg = useRegistry();
  const [d, setD] = useState<Draft>({
    id: "my-study-v1",
    title:
      "Does market-local weather improve maize price forecasts in East Africa?",
    question:
      "Do market-local rainfall and temperature anomalies improve 1- and 3-month maize price forecasts beyond price history?",
    hypothesis:
      "Adding market-local weather anomalies to price history lowers country-balanced forecast loss.",
    estimand:
      "Ratio of country-balanced mean squared forecast errors, family B over family A, on matched forecasts.",
    studyType: "predictive",
    confirmatory: false,
    countries: ["ETH", "RWA", "SDN", "TZA", "UGA"],
    categories: "cereals and tubers",
    horizons: [1, 3],
    testStart: "2022-01-01",
    robustness: ["price_lag_0", "leave_one_country_out"],
    controls: ["weather_time_shift_60"],
    seed: 20261117,
  });
  const [edited, setEdited] = useState<string | null>(null);
  const [result, setResult] = useState<Validation | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const yaml = edited ?? toYaml(d);
  const up = (patch: Partial<Draft>) => {
    setD((x) => ({ ...x, ...patch }));
    setEdited(null);
    setResult(null);
  };
  const rows = useMemo(
    () => (reg.data?.countries ?? []).filter((r) => r.observations),
    [reg.data],
  );
  const shown = rows.filter(
    (r) =>
      !filter ||
      r.name.toLowerCase().includes(filter.toLowerCase()) ||
      r.country_iso3 === filter.toUpperCase(),
  );

  async function validate() {
    setBusy(true);
    setErr(null);
    try {
      setResult(await validateSpec(yaml));
    } catch (e) {
      setErr(e);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-6">
        <Panel title="1. Question">
          <div className="space-y-3">
            <Field label="Study id (lower-case, versioned)" htmlFor="wb-id">
              <input
                id="wb-id"
                className={inputClass}
                value={d.id}
                onChange={(e) => up({ id: e.target.value })}
              />
            </Field>
            {(["title", "question", "hypothesis", "estimand"] as const).map(
              (k) => (
                <Field
                  key={k}
                  label={k[0].toUpperCase() + k.slice(1)}
                  htmlFor={`wb-${k}`}
                >
                  <textarea
                    id={`wb-${k}`}
                    rows={k === "title" ? 1 : 2}
                    className={inputClass}
                    value={d[k]}
                    onChange={(e) => up({ [k]: e.target.value })}
                  />
                </Field>
              ),
            )}
            <fieldset className="flex flex-wrap gap-4 text-sm">
              <legend className="mb-1 text-xs text-ink-3">Study type</legend>
              {(["predictive", "associational", "descriptive"] as const).map(
                (t) => (
                  <label key={t} className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="wb-type"
                      checked={d.studyType === t}
                      onChange={() =>
                        up({
                          studyType: t,
                          confirmatory:
                            t === "descriptive" ? false : d.confirmatory,
                        })
                      }
                    />
                    {t}
                  </label>
                ),
              )}
              <label
                className="flex items-center gap-1.5 text-ink-3"
                title="No estimator with identification diagnostics is implemented"
              >
                <input type="radio" disabled /> causal (not supported)
              </label>
            </fieldset>
            <Check
              label="Confirmatory (pre-registered)"
              checked={d.confirmatory}
              onChange={(v) => up({ confirmatory: v })}
              hint="Requires hypotheses, multiplicity correction and controls, and must be frozen with a clean git tree before it is run."
            />
          </div>
        </Panel>
        <Panel
          title="2. Population"
          note={`${d.countries.length} selected. Only countries with stored WFP prices are listed.`}
        >
          {reg.isLoading && <Loading label="Loading registry" />}
          {reg.error && (
            <ErrorState error={reg.error} what="the coverage registry" />
          )}
          {rows.length > 0 && (
            <>
              <div className="mb-2 flex flex-wrap gap-2">
                <input
                  aria-label="Filter countries"
                  placeholder="Filter"
                  className={`${inputClass} max-w-[12rem]`}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <button
                  type="button"
                  className="rounded border border-line px-2 py-1 text-xs"
                  onClick={() =>
                    up({
                      countries: rows
                        .filter(
                          (r) =>
                            r.status === "research_eligible" ||
                            r.status === "forecast_evaluated",
                        )
                        .map((r) => r.country_iso3),
                    })
                  }
                >
                  All research-eligible
                </button>
                <button
                  type="button"
                  className="rounded border border-line px-2 py-1 text-xs"
                  onClick={() => up({ countries: [] })}
                >
                  Clear
                </button>
              </div>
              <div className="grid max-h-56 grid-cols-2 gap-x-3 overflow-y-auto sm:grid-cols-3">
                {shown.map((r) => (
                  <Check
                    key={r.country_iso3}
                    label={`${r.name} (${r.country_iso3})`}
                    checked={d.countries.includes(r.country_iso3)}
                    onChange={(v) =>
                      up({
                        countries: v
                          ? [...d.countries, r.country_iso3].sort()
                          : d.countries.filter((c) => c !== r.country_iso3),
                      })
                    }
                  />
                ))}
              </div>
            </>
          )}
          <div className="mt-3">
            <Field
              label="Commodity categories (comma-separated, WFP categories)"
              htmlFor="wb-cat"
            >
              <input
                id="wb-cat"
                className={inputClass}
                value={d.categories}
                onChange={(e) => up({ categories: e.target.value })}
              />
            </Field>
          </div>
        </Panel>
        {d.studyType === "predictive" && (
          <Panel
            title="3. Forecast design"
            note={`Families: A = ${FAMILIES.A}; B = ${FAMILIES.B}. One hypothesis (B vs A) per horizon.`}
          >
            <div className="space-y-3">
              <fieldset className="flex flex-wrap gap-4 text-sm">
                <legend className="mb-1 text-xs text-ink-3">
                  Horizons (months)
                </legend>
                {[1, 2, 3, 6].map((h) => (
                  <Check
                    key={h}
                    label={String(h)}
                    checked={d.horizons.includes(h)}
                    onChange={(v) =>
                      up({
                        horizons: v
                          ? [...d.horizons, h].sort((a, b) => a - b)
                          : d.horizons.filter((x) => x !== h),
                      })
                    }
                  />
                ))}
              </fieldset>
              <Field
                label="First forecast origin of the evaluation sample"
                htmlFor="wb-start"
              >
                <input
                  id="wb-start"
                  type="date"
                  className={inputClass}
                  value={d.testStart}
                  onChange={(e) => up({ testStart: e.target.value })}
                />
              </Field>
            </div>
          </Panel>
        )}
        {d.studyType !== "descriptive" && (
          <Panel
            title="4. Robustness and negative controls"
            note="A negative control should not reproduce the main result; if it does, the result is suspect."
          >
            <div className="grid gap-2 sm:grid-cols-2">
              {ROBUSTNESS.map((r) => (
                <Check
                  key={r}
                  label={r.replaceAll("_", " ")}
                  checked={d.robustness.includes(r)}
                  onChange={(v) =>
                    up({
                      robustness: v
                        ? [...d.robustness, r]
                        : d.robustness.filter((x) => x !== r),
                    })
                  }
                />
              ))}
              {d.studyType === "predictive" &&
                CONTROLS.map((r) => (
                  <Check
                    key={r}
                    label={`${r.replaceAll("_", " ")} (control)`}
                    checked={d.controls.includes(r)}
                    onChange={(v) =>
                      up({
                        controls: v
                          ? [...d.controls, r]
                          : d.controls.filter((x) => x !== r),
                      })
                    }
                  />
                ))}
            </div>
          </Panel>
        )}
      </div>

      <div className="space-y-6 lg:sticky lg:top-4 lg:self-start">
        <Panel title="Metadata preview">
          {rows.length > 0 ? (
            <Preview rows={rows} picked={d.countries} />
          ) : (
            <p className="text-sm text-ink-3">Registry unavailable.</p>
          )}
        </Panel>
        <Panel
          title="Specification"
          note={
            edited !== null
              ? "Edited by hand; form changes will replace your edits."
              : "Generated from the form. You can edit it directly."
          }
          actions={
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded bg-ink px-3 py-1.5 text-sm text-bg disabled:opacity-50"
                onClick={validate}
                disabled={busy}
              >
                {busy ? "Checking…" : "Validate"}
              </button>
              <button
                type="button"
                className="rounded border border-line px-3 py-1.5 text-sm"
                onClick={() => navigator.clipboard?.writeText(yaml)}
              >
                Copy
              </button>
              <button
                type="button"
                className="rounded border border-line px-3 py-1.5 text-sm"
                onClick={() =>
                  download(`${d.id || "spec"}.yaml`, yaml, "text/yaml")
                }
              >
                Download
              </button>
            </div>
          }
        >
          <textarea
            aria-label="Specification YAML"
            spellCheck={false}
            className="h-80 w-full rounded border border-line bg-surface-2 p-3 font-mono text-xs"
            value={yaml}
            onChange={(e) => {
              setEdited(e.target.value);
              setResult(null);
            }}
          />
          <div aria-live="polite" className="mt-3 space-y-2">
            {err != null && <ErrorState error={err} what="validation" />}
            {result?.valid && (
              <div className="space-y-2 text-sm">
                <div className="flex flex-wrap gap-2">
                  <Tag tone="good">valid</Tag>
                  <Tag>{result.study_type}</Tag>
                  <Tag
                    tone={
                      result.evidence_class === "confirmatory"
                        ? "good"
                        : "muted"
                    }
                  >
                    {result.evidence_class}
                  </Tag>
                </div>
                <p className="break-all font-mono text-xs text-ink-3">
                  sha256 {result.spec_hash}
                </p>
                <p>Run it locally from a clone of the repository:</p>
                <pre className="overflow-x-auto rounded bg-surface-2 p-3 text-xs">
                  {(result.run_locally ?? []).map((c) => `${c}`).join("\n")}
                </pre>
              </div>
            )}
            {result && !result.valid && (
              <div className="text-sm">
                <Tag tone="warn">
                  {result.problems.length} problem
                  {result.problems.length === 1 ? "" : "s"}
                </Tag>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-2">
                  {result.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
