"use client";

import { clsx } from "clsx";
import { AlertTriangle, Info, Loader2 } from "lucide-react";
import Link from "next/link";

import { ApiError, LOCAL_API } from "@/lib/api";
import { VERDICT } from "@/lib/format";

export function cn(...a: Parameters<typeof clsx>) {
  return clsx(...a);
}

export function PageHeader({ title, lede, children }: { title: string; lede: React.ReactNode; children?: React.ReactNode }) {
  return (
    <header className="mb-8 flex flex-col gap-4 border-b border-line pb-6 md:flex-row md:items-end md:justify-between">
      <div className="max-w-3xl">
        <h1 className="font-serif text-4xl leading-tight text-ink md:text-5xl">{title}</h1>
        <p className="mt-3 text-lg text-ink-2">{lede}</p>
      </div>
      {children && <div className="flex flex-wrap items-end gap-3">{children}</div>}
    </header>
  );
}

export function Panel({
  title,
  note,
  children,
  className,
  actions,
  id,
}: {
  title?: string;
  note?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  actions?: React.ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className={cn("min-w-0 rounded-md border border-line bg-surface p-5", className)} aria-label={title}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
            {note && <p className="mt-0.5 text-sm text-ink-3">{note}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-10 text-sm text-ink-3">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorState({ error, what }: { error: unknown; what: string }) {
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  const offline = error instanceof ApiError && error.status === 0;
  return (
    <div role="alert" className="flex gap-3 rounded-md border border-bad/40 bg-bad/5 p-4 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-hidden />
      <div>
        <p className="font-medium text-ink">Could not load {what}.</p>
        <p className="mt-1 text-ink-2">{msg}</p>
        {offline && LOCAL_API && <p className="mt-1 text-ink-3">Check that the API is running and NEXT_PUBLIC_API_URL points to it.</p>}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-line p-6 text-sm text-ink-2">{children}</div>;
}

export function Note({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={cn("flex gap-2.5 rounded-md p-3 text-sm", tone === "warn" ? "bg-warn/10 text-ink" : "bg-surface-2 text-ink-2")}>
      {tone === "warn" ? (
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
      ) : (
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-rain" aria-hidden />
      )}
      <div>{children}</div>
    </div>
  );
}

const toneClass = {
  good: "bg-good/12 text-good border-good/30",
  neutral: "bg-neutral/12 text-ink-2 border-neutral/30",
  warn: "bg-warn/12 text-warn border-warn/35",
  muted: "bg-surface-2 text-ink-3 border-line",
};

export function VerdictBadge({ verdict, short = true }: { verdict?: string | null; short?: boolean }) {
  const v = VERDICT[verdict ?? ""] ?? { label: verdict ?? "Not run", short: verdict ?? "Not run", tone: "muted" as const };
  return (
    <span className={cn("inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium", toneClass[v.tone])}>
      {short ? v.short : v.label}
    </span>
  );
}

export function Tag({ children, tone = "muted" }: { children: React.ReactNode; tone?: keyof typeof toneClass }) {
  return <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-xs", toneClass[tone])}>{children}</span>;
}

export function Field({ label, children, htmlFor }: { label: string; children: React.ReactNode; htmlFor: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-ink-3">
        {label}
      </label>
      {children}
    </div>
  );
}

export const inputClass =
  "h-9 min-w-0 rounded border border-line bg-surface px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-rain";

export function Select({
  id,
  value,
  onChange,
  options,
  placeholder,
  className,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  className?: string;
}) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputClass, "pr-7", className)}>
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function ButtonLink({ href, children, variant = "primary" }: { href: string; children: React.ReactNode; variant?: "primary" | "quiet" }) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex h-10 items-center rounded px-4 text-sm font-medium transition-colors",
        variant === "primary" ? "bg-ink text-bg hover:bg-ink-2" : "border border-line text-ink hover:bg-surface-2",
      )}
    >
      {children}
    </Link>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-0.5 text-lg font-medium text-ink">{value}</div>
      {hint && <div className="text-xs text-ink-3">{hint}</div>}
    </div>
  );
}
