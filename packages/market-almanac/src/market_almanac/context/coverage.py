"""Coverage of the economic-context data, country by country, as it actually is in a snapshot.

Nothing here is a target: a country is "complete" only when its headline CPI, food CPI and exchange-rate series are all
present and current, and the matrix says so per cell. The Markdown form is what ``docs/ECONOMIC_CONTEXT_COVERAGE.md``
publishes, so a reader sees which countries can and cannot be given which context.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from market_almanac.context.reference import regime_for
from market_almanac.context.store import ContextSnapshot

IMF_CONCEPTS = ("cpi_headline", "cpi_food", "fx_period_avg", "fx_end_period")
FRESH_MONTHS = 6  # a series ending more than this many months before the newest month anywhere is "stale"
MIN_MONTHS = 36  # fewer valid months than this cannot support a year-on-year history worth showing


def _months(ts: str | None) -> int | None:
    return None if not ts else int(ts[:4]) * 12 + int(ts[5:7])


def coverage_matrix(snap: ContextSnapshot) -> pd.DataFrame:
    """One row per country: for each IMF concept ``first``, ``last``, ``n`` and a ``state`` of
    ``current | stale | short | none``; plus the exchange-rate regime classification and an overall ``usable`` label."""
    t = snap.series_table()
    imf = t[t["provider"] == "imf"]
    newest = max((_months(x) or 0) for x in imf["last_period"].dropna()) if len(imf) else 0
    rows: list[dict[str, Any]] = []
    for iso3 in sorted(imf["country_iso3"].dropna().unique()):
        row: dict[str, Any] = {"country": iso3}
        for c in IMF_CONCEPTS:
            r = snap.row(f"imf.{c}.{iso3}")
            if r is None or not r["n_obs"]:
                row |= {f"{c}_first": None, f"{c}_last": None, f"{c}_n": 0, f"{c}_state": "none"}
                continue
            last = _months(r["last_period"]) or 0
            state = "stale" if newest - last > FRESH_MONTHS else ("short" if r["n_obs"] < MIN_MONTHS else "current")
            row |= {
                f"{c}_first": r["first_period"],
                f"{c}_last": r["last_period"],
                f"{c}_n": int(r["n_obs"]),
                f"{c}_state": state,
                f"{c}_base_breaks": r["base_breaks"] or "",
            }
        regs = regime_for(iso3)
        row["regime"] = ",".join(sorted(e["id"] for e in regs)) or "not classified"
        ok = {c: row[f"{c}_state"] == "current" for c in IMF_CONCEPTS}
        fx = ok["fx_period_avg"] or ok["fx_end_period"]
        if ok["cpi_headline"] and ok["cpi_food"] and fx:
            row["usable"] = "full"
        elif ok["cpi_headline"] and fx:
            row["usable"] = "headline CPI + FX (no current food CPI)"
        elif ok["cpi_headline"]:
            row["usable"] = "headline CPI only"
        elif fx:
            row["usable"] = "FX only"
        else:
            row["usable"] = "none current"
        rows.append(row)
    return pd.DataFrame(rows)


def _cell(r: pd.Series, c: str) -> str:
    return f"{r[f'{c}_first']}–{r[f'{c}_last']} ({r[f'{c}_n']})" if r[f"{c}_n"] else "none"


def coverage_summary(m: pd.DataFrame) -> dict[str, Any]:
    return {
        "countries": len(m),
        "usable": {k: int(v) for k, v in m["usable"].value_counts().items()},
        "by_concept": {c: {k: int(v) for k, v in m[f"{c}_state"].value_counts().items()} for c in IMF_CONCEPTS},
    }


def coverage_for(m: pd.DataFrame, countries: list[str]) -> pd.DataFrame:
    return m[m["country"].isin(countries)].reset_index(drop=True)


def to_markdown(m: pd.DataFrame, countries: list[str] | None = None) -> str:
    """The summary and, for ``countries`` (default: every country with price data is the caller's choice), a table."""
    s = coverage_summary(m)
    out = ["| Overall usability | Countries |", "|---|---:|"]
    out += [f"| {k} | {v} |" for k, v in sorted(s["usable"].items(), key=lambda kv: -kv[1])]
    out += ["", "| Concept | current | stale | short | none |", "|---|---:|---:|---:|---:|"]
    for c, d in s["by_concept"].items():
        out.append(f"| {c} | " + " | ".join(str(d.get(k, 0)) for k in ("current", "stale", "short", "none")) + " |")
    if countries is not None:
        sub = coverage_for(m, countries)
        out += ["", "| Country | Headline CPI | Food CPI | FX avg | Regime | Usable |", "|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            cells = [_cell(r, c) for c in ("cpi_headline", "cpi_food", "fx_period_avg")]
            out.append(f"| {r['country']} | {' | '.join(cells)} | {r['regime']} | {r['usable']} |")
    return "\n".join(out) + "\n"
