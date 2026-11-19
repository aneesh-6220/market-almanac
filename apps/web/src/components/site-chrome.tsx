"use client";

import { Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { LOCAL_API } from "@/lib/api";
import { useStatus } from "@/lib/queries";

import { cn } from "./ui";

const NAV = [
  { href: "/explorer", label: "Explore" },
  { href: "/compare", label: "Compare" },
  { href: "/investigate", label: "Investigate" },
  { href: "/forecasts", label: "Forecasts" },
  { href: "/atlas", label: "Global" },
  { href: "/forecastability", label: "Forecastability" },
  { href: "/studies", label: "Studies" },
  { href: "/workbench", label: "Workbench" },
  { href: "/lab", label: "Research Lab" },
  { href: "/data", label: "Data" },
  { href: "/methodology", label: "Methodology" },
  { href: "/about", label: "About" },
];

function subscribeTheme(cb: () => void) {
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", cb);
  return () => {
    mo.disconnect();
    mq.removeEventListener("change", cb);
  };
}

function currentTheme(): "light" | "dark" {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => null);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("st-theme", next);
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      type="button"
      onClick={toggle}
      className="inline-flex h-9 w-9 items-center justify-center rounded text-ink-2 hover:bg-surface-2"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function Wordmark() {
  // The mark: a price line that jumps after a dry spell (two bars), drawn as a single stroke.
  return (
    <Link href="/" className="flex items-center gap-2 text-ink" aria-label="Market Almanac home">
      <svg width="26" height="20" viewBox="0 0 26 20" aria-hidden>
        <rect x="1" y="12" width="3" height="7" rx="1" fill="var(--rain)" />
        <rect x="5.5" y="15" width="3" height="4" rx="1" fill="var(--rain)" opacity="0.6" />
        <path d="M1 9 L8 9 L12 8 L15 3 L19 5 L25 2" fill="none" stroke="var(--grain)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="font-serif text-xl tracking-tight">Market Almanac</span>
    </Link>
  );
}

export function SiteHeader() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <header className="border-b border-line bg-surface/80 backdrop-blur print:hidden">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 md:px-6">
        <Wordmark />
        <nav aria-label="Main" className="hidden items-center gap-0.5 xl:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={path.startsWith(n.href) ? "page" : undefined}
              className={cn(
                "rounded px-2.5 py-1.5 text-sm",
                path.startsWith(n.href) ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <button
            type="button"
            className="rounded px-2 py-1.5 text-sm text-ink-2 xl:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
          >
            Menu
          </button>
        </div>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label="Main" className="border-t border-line px-4 py-2 xl:hidden">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="block py-2 text-sm text-ink">
              {n.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

/** Persistent band shown on every page while the API serves synthetic demo data. */
export function ModeBand() {
  const { data, isError } = useStatus();
  if (isError) {
    return (
      <div className="border-b border-bad/30 bg-bad/5 px-4 py-1.5 text-center text-sm text-ink-2" role="status">
        {LOCAL_API
          ? "The Market Almanac API is unreachable. Pages will show errors until it is running."
          : "The Market Almanac data service is temporarily unavailable. Pages will show errors until it is back."}
      </div>
    );
  }
  if (!data) return null;
  if (data.synthetic) {
    return (
      <div className="synthetic-band border-b border-warn/40 px-4 py-1.5 text-center text-sm text-ink" role="status" data-testid="synthetic-band">
        <strong className="font-semibold">Demo mode.</strong> Every number on this site describes synthetic data for the
        fictional country Demoland. Nothing here is evidence about real markets.
      </div>
    );
  }
  return (
    <div className="border-b border-line bg-surface px-4 py-1.5 text-center text-sm text-ink-2" role="status">
      Real data from public providers. Prices are shown with the month observed; statistical results are not causal estimates.
    </div>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-20 border-t border-line print:hidden">
      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-10 text-sm text-ink-3 md:grid-cols-3 md:px-6">
        <div>
          <Wordmark />
          <p className="mt-2 max-w-xs">Open-source food-price intelligence and forecast accountability. MIT-licensed code.</p>
        </div>
        <p>
          Data: WFP via HDX HAPI · NASA POWER · IFPRI MapSPAM · World Bank · IMF · FAOSTAT. Each source keeps its own licence;
          see <Link className="underline" href="/data">Data &amp; provenance</Link>.
        </p>
        <p>
          Forecasts here are statistical predictions with stated uncertainty. They are not trading advice and do not
          establish causes.
        </p>
      </div>
    </footer>
  );
}
