export const VERDICT: Record<string, { label: string; tone: "good" | "neutral" | "warn" | "muted"; short: string }> = {
  improved: { label: "Environmental features improved prediction", short: "Improved", tone: "good" },
  not_improved: { label: "Environmental features did not improve prediction", short: "Not improved", tone: "neutral" },
  inconsistent: { label: "Results were inconsistent", short: "Inconsistent", tone: "warn" },
  insufficient_evidence: { label: "Evidence was insufficient", short: "Insufficient", tone: "muted" },
};

export const MODEL_LABEL: Record<string, string> = {
  naive: "Naive (no change)",
  seasonal_naive: "Seasonal naive",
  climatology: "Base rate",
  ridge_A: "Ridge · price only (A)",
  ridge_B: "Ridge · + weather (B)",
  ridge_C: "Ridge · + macro (C)",
  ridge_D: "Ridge · + agriculture (D)",
  enet_A: "Elastic net (A)",
  enet_B: "Elastic net (B)",
  gbr_A: "Boosting (A)",
  gbr_B: "Boosting (B)",
  logit_A: "Logistic · price only (A)",
  logit_B: "Logistic · + weather (B)",
  logit_C: "Logistic · + macro (C)",
  logit_D: "Logistic · + agriculture (D)",
  gbc_A: "Boosting clf. (A)",
  gbc_B: "Boosting clf. (B)",
};

export const modelLabel = (m: string) => MODEL_LABEL[m] ?? m;

export function fmt(v: unknown, digits = 3): string {
  if (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v))) return "—";
  if (typeof v !== "number") return String(v);
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return Number(v.toPrecision(digits)).toString();
}

export function pct(v: unknown, digits = 0): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function pValue(p: unknown): string {
  if (typeof p !== "number" || !Number.isFinite(p)) return "—";
  if (p < 0.001) return "< 0.001";
  return p.toFixed(3);
}

export function month(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d.length === 7 ? `${d}-01` : d);
  return dt.toLocaleDateString("en", { year: "numeric", month: "short", timeZone: "UTC" });
}

export function dateTime(d: string | null | undefined): string {
  if (!d) return "never";
  return new Date(d).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function download(filename: string, content: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
