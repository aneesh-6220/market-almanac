"""World Bank Commodity Price Data ("Pink Sheet"): discovery, retrieval and parsing of the monthly workbook.

The Pink Sheet is a spreadsheet (``CMO-Historical-Data-Monthly.xlsx``) whose address contains a hash that changes with
every monthly release, so the current address is read from the Commodity Markets page. Only the benchmarks named in
``data/benchmark_mappings.json`` are extracted (14 series, not the 70-odd in the workbook), each with its unit
**checked** against the unit the mapping expects: if the World Bank redefines a series' unit the ingest fails instead
of silently mixing units. The workbook's own definition and sources for each extracted series are kept next to the
data, because a "rice benchmark" is a specific grade at a specific place.

Revisions: the World Bank states that its most recent months can be estimates and revises them; each retrieval is
an immutable snapshot and :mod:`market_almanac.context.store` records what changed between snapshots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.context.reference import benchmark_table
from market_almanac.context.xlsx import column_index, read_workbook
from market_almanac.http import HttpClient

COMMODITY_PAGE = "https://www.worldbank.org/en/research/commodity-markets"
_URL_RE = re.compile(r"https://thedocs\.worldbank\.org/en/doc/[0-9a-f\-]+/related/CMO-Historical-Data-Monthly\.xlsx")
_PERIOD_RE = re.compile(r"^(\d{4})M(\d{2})$")
_MISSING = {"", "…", "...", "..", "n/a", "na", "-", "—"}
UNIT_MAP = {
    "($/mt)": "USD per metric ton",
    "($/kg)": "USD per kilogram",
    "($/bbl)": "USD per barrel",
}
LICENSE_NOTE = (
    "World Bank datasets are published under CC BY 4.0 unless labelled otherwise "
    "(https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets); the Pink Sheet's series are compiled by the "
    "World Bank from third-party price sources named in the workbook's Description sheet, and the workbook itself does "
    "not state a licence. Treated as 'unconfirmed' for public redistribution until the World Bank confirms."
)


class PinkSheetError(ValueError):
    """The workbook does not have the expected structure, or a series' definition changed."""


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("*", "")).strip().lower()


def find_workbook_url(html: str) -> str:
    """The current monthly-workbook address from the Commodity Markets page."""
    m = _URL_RE.search(html)
    if not m:
        raise PinkSheetError("the Commodity Markets page no longer links CMO-Historical-Data-Monthly.xlsx")
    return m.group(0)


async def discover_workbook_url(http: HttpClient) -> str:
    return find_workbook_url(await http.get_text(COMMODITY_PAGE, use_cache=False))


@dataclass
class PinkSheetParse:
    observations: pd.DataFrame  # series_key, period, value
    series: list[dict[str, Any]]
    updated_on: str | None
    rejected: list[dict[str, Any]]
    n_months: int


def parse_workbook(path: Path) -> PinkSheetParse:
    """Extract the mapped benchmarks from a Pink Sheet workbook (see module docstring)."""
    sheets = read_workbook(path)
    if "Monthly Prices" not in sheets:
        raise PinkSheetError("no 'Monthly Prices' sheet")
    rows = sheets["Monthly Prices"]
    updated = None
    for r in sorted(rows)[:6]:
        for v in rows[r].values():
            m = re.search(r"Updated on ([A-Za-z]+ \d{1,2}, \d{4})", v)
            if m:
                updated = m.group(1)
    header_row = next((r for r in sorted(rows) if "A" not in rows[r] and len(rows[r]) > 10), None)
    if header_row is None:
        raise PinkSheetError("cannot find the header row of the Monthly Prices sheet")
    names, units = rows[header_row], rows.get(header_row + 1, {})
    by_name = {_norm(v): col for col, v in names.items() if col != "A"}

    table = benchmark_table()
    descriptions = _descriptions(sheets.get("Description", {}))
    series: list[dict[str, Any]] = []
    cols: dict[str, str] = {}
    for bid, b in table["benchmarks"].items():
        col = by_name.get(_norm(b["pink_name"]))
        if col is None:
            raise PinkSheetError(f"benchmark {b['pink_name']!r} is no longer in the Pink Sheet header")
        unit = UNIT_MAP.get(units.get(col, "").strip().lower())
        if unit != b["unit"]:
            raise PinkSheetError(
                f"benchmark {b['pink_name']!r}: the workbook's unit {units.get(col)!r} "
                f"is not the expected {b['unit']!r}"
            )
        cols[bid] = col
        series.append(
            {
                "benchmark_id": bid,
                "series_key": f"wb.pink.{bid}",
                "pink_name": b["pink_name"],
                "label": b["label"],
                "unit": unit,
                "definition": descriptions.get(bid),
            }
        )
    recs: list[tuple[str, pd.Timestamp, float]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    n_months = 0
    for r in sorted(rows):
        if r <= header_row + 1:
            continue
        label = rows[r].get("A", "").strip()
        m = _PERIOD_RE.match(label)
        if not m:
            continue
        if label in seen:
            rejected.append({"series_key": "wb.pink.*", "period": label, "value": None, "reason": "duplicate_month"})
            continue
        seen.add(label)
        n_months += 1
        period = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        for bid, col in cols.items():
            raw = rows[r].get(col, "").strip()
            if raw.lower() in _MISSING:
                continue
            try:
                val = float(raw)
            except ValueError:
                rejected.append(
                    {"series_key": f"wb.pink.{bid}", "period": label, "value": raw, "reason": "unparseable"}
                )
                continue
            if not val > 0:
                rejected.append(
                    {"series_key": f"wb.pink.{bid}", "period": label, "value": raw, "reason": "non_positive"}
                )
                continue
            recs.append((f"wb.pink.{bid}", period, val))
    obs = pd.DataFrame(recs, columns=["series_key", "period", "value"])
    return PinkSheetParse(obs, series, updated, rejected, n_months)


def _descriptions(rows: dict[int, dict[str, str]]) -> dict[str, dict[str, str]]:
    """The workbook's Description sheet: for each mapped benchmark, its definition and the sources it names."""
    table = benchmark_table()["benchmarks"]
    flat: list[tuple[str, str]] = []
    for r in sorted(rows):
        cells = [v for _, v in sorted(rows[r].items(), key=lambda kv: column_index(kv[0]))]
        if len(cells) >= 2 and len(cells[-2]) > 12:  # rows are [flag marks,] description, sources
            flat.append((cells[-2], cells[-1]))
    out: dict[str, dict[str, str]] = {}
    for bid, b in table.items():
        pref = _norm(b["description_prefix"])
        for text, sources in flat:
            if _norm(text).startswith(pref):
                out[bid] = {"text": re.sub(r"\s+", " ", text).strip(), "sources": re.sub(r"\s+", " ", sources).strip()}
                break
    return out
