"use client";

import { Check, Copy, Share2 } from "lucide-react";
import { useState } from "react";

import { MOVEMENT_LABEL } from "@/lib/market-api";

import { Tag } from "./ui";

export function MovementTag({ label }: { label: string }) {
  const m = MOVEMENT_LABEL[label] ?? { text: label.replace(/_/g, " "), tone: "muted" as const };
  return <Tag tone={m.tone}>{m.text}</Tag>;
}

/** Copies text to the clipboard and confirms it, with a fallback message when the browser refuses. */
export function CopyButton({ text, label, icon = "copy" }: { text: () => string; label: string; icon?: "copy" | "share" }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const Icon = state === "done" ? Check : icon === "share" ? Share2 : Copy;
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text());
          setState("done");
        } catch {
          setState("failed");
        }
        setTimeout(() => setState("idle"), 2500);
      }}
      className="inline-flex h-8 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2"
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      <span aria-live="polite">{state === "done" ? "Copied" : state === "failed" ? "Copy not permitted" : label}</span>
    </button>
  );
}

export function LinkButton({ href, children, download }: { href: string; children: React.ReactNode; download?: boolean }) {
  return (
    <a href={href} download={download} className="inline-flex h-8 items-center gap-1.5 rounded border border-line px-2.5 text-sm text-ink hover:bg-surface-2">
      {children}
    </a>
  );
}

export const signedPct = (v: number | null | undefined, digits = 1) =>
  v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export const z1 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);

export const MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
