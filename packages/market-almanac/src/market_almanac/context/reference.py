"""Curated reference tables: currency regimes and commodity-to-benchmark mappings.

Both are versioned JSON next to this module (reviewed by hand, not scraped) and validated on load. They are data, not
code, so a correction is a reviewed diff to a table with its source named.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).with_name("data")
CONFIDENCE = ("high", "medium", "low", "none")
REGIME_KINDS = ("currency_union_peg", "peg", "dollarized", "official_rate_caution")


class ReferenceTableError(ValueError):
    """A reference table is malformed."""


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("*", "")).strip().lower()


@lru_cache(maxsize=1)
def regimes() -> dict[str, Any]:
    doc = json.loads((DATA / "currency_regimes.json").read_text())
    seen: dict[str, dict[str, Any]] = {}
    for e in doc["entries"]:
        if e["kind"] not in REGIME_KINDS:
            raise ReferenceTableError(f"regime {e['id']}: unknown kind {e['kind']!r}")
        for c in e["countries"]:
            if not re.fullmatch(r"[A-Z]{3}", c):
                raise ReferenceTableError(f"regime {e['id']}: bad country code {c!r}")
            # a country may appear under a peg and under the official-rate caution, never under two pegs
            if c in seen and "official_rate_caution" not in (e["kind"], seen[c]["kind"]):
                raise ReferenceTableError(f"{c} is in two exchange-rate regimes: {seen[c]['id']} and {e['id']}")
            if e["kind"] != "official_rate_caution" or c not in seen:
                seen[c] = e
    return doc


def regime_for(iso3: str) -> list[dict[str, Any]]:
    """Every regime entry that lists the country (a peg and an official-rate caution can both apply)."""
    return [e for e in regimes()["entries"] if iso3 in e["countries"]]


@lru_cache(maxsize=1)
def benchmark_table() -> dict[str, Any]:
    doc = json.loads((DATA / "benchmark_mappings.json").read_text())
    ids = set(doc["benchmarks"])
    index: dict[str, dict[str, Any]] = {}
    for m in doc["mappings"]:
        if m["confidence"] not in CONFIDENCE:
            raise ReferenceTableError(f"mapping {m['commodities']}: unknown confidence {m['confidence']!r}")
        if m["confidence"] == "none" and m["benchmarks"]:
            raise ReferenceTableError(f"mapping {m['commodities']}: confidence 'none' cannot name a benchmark")
        if m["confidence"] != "none" and not m["benchmarks"]:
            raise ReferenceTableError(f"mapping {m['commodities']}: a mapping needs a benchmark or confidence 'none'")
        if m["confidence"] != "none" and not m["limitations"]:
            raise ReferenceTableError(f"mapping {m['commodities']}: every mapping must state its limitations")
        for b in m["benchmarks"]:
            if b not in ids:
                raise ReferenceTableError(f"mapping {m['commodities']}: unknown benchmark {b!r}")
        for c in m["commodities"]:
            if _norm(c) in index:
                raise ReferenceTableError(f"commodity {c!r} is mapped twice")
            index[_norm(c)] = m
    doc["_index"] = index
    return doc


def benchmark_mapping(commodity_name: str) -> dict[str, Any]:
    """The mapping for a WFP commodity name, or an explicit 'none' mapping. Exact names only: a variant that is not
    listed (for example 'Rice (parboiled)') is not silently assigned the nearest benchmark."""
    t = benchmark_table()
    m = t["_index"].get(_norm(commodity_name))
    if m is None:
        return {
            "commodities": [commodity_name],
            "benchmarks": [],
            "confidence": "none",
            "role": "not mapped",
            "limitations": [t["no_benchmark_note"]],
        }
    return m


def benchmark_def(benchmark_id: str) -> dict[str, Any]:
    return benchmark_table()["benchmarks"][benchmark_id]


def pink_name_to_id(pink_name: str) -> str | None:
    n = _norm(pink_name)
    for k, v in benchmark_table()["benchmarks"].items():
        if _norm(v["pink_name"]) == n:
            return k
    return None
