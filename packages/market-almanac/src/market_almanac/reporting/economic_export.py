"""The economic-context parts of the research brief and its CSV tables, read from the investigation document.

Nothing here computes: every figure is taken from ``doc["context"]["economic"]`` and ``doc["evidence"]["economic"]``,
so the brief can be checked against the JSON export. Missing values stay missing (empty cells, "not available" text);
they are never filled with zero.
"""

from __future__ import annotations

from typing import Any

from market_almanac.analytics.evidence import month_name, pct

ECONOMIC_TABLES = (
    "economic_series",
    "economic_changes",
    "economic_lags",
    "economic_lineage",
    "economic_notes",
)


def _eco(doc: dict[str, Any]) -> dict[str, Any] | None:
    eco = doc.get("context", {}).get("economic")
    return eco if eco and eco.get("status") == "ok" else None


def _indicators(eco: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every indicator the section holds, with a stable column prefix."""
    out: list[tuple[str, dict[str, Any]]] = [
        ("headline_cpi", eco["inflation"]["headline"]),
        ("food_cpi", eco["inflation"]["food"]),
        ("fx_period_average", eco["exchange_rate"]["period_average"]),
        ("fx_end_period", eco["exchange_rate"]["end_period"]),
    ]
    out += [
        (f"benchmark_{it.get('benchmark_id', i)}", it) for i, it in enumerate(eco["international"].get("items", []))
    ]
    return out


def economic_table_rows(doc: dict[str, Any], table: str) -> list[dict[str, Any]]:
    eco = _eco(doc)
    if eco is None:
        return []
    if table == "economic_series":
        months = eco["charts"]["months"]
        cols: dict[str, list[Any]] = {"price_index": eco["price"]["chart_index"]}
        if eco.get("usd_price"):
            cols["price_in_usd_index"] = eco["usd_price"]["chart_index"]
        for prefix, ind in _indicators(eco):
            if ind.get("chart_index"):
                cols[f"{prefix}_index"] = ind["chart_index"]
            lc = ind.get("local_currency")
            if lc and lc.get("chart_index"):
                cols[f"{prefix}_local_currency_index"] = lc["chart_index"]
        return [{"period": m, **{k: v[i] for k, v in cols.items()}} for i, m in enumerate(months)]
    if table == "economic_changes":
        rows: list[dict[str, Any]] = [
            {
                "item": "local price",
                "series_key": doc["subject"]["series_id"],
                "state": "ok",
                "yoy_pct": eco["price"]["yoy_pct"],
                "baseline_to_peak_pct": eco["price"]["baseline_to_peak_pct"],
                "mom_pct": None,
                "reason": None,
            }
        ]
        for _prefix, ind in _indicators(eco):
            rows.append(
                {
                    "item": ind["label"],
                    "series_key": ind["series_key"],
                    "state": ind["state"],
                    "yoy_pct": ind.get("yoy_pct"),
                    "baseline_to_peak_pct": ind.get("baseline_to_peak_pct"),
                    "mom_pct": ind.get("mom_pct"),
                    "reason": ind.get("reason") or ind.get("yoy_unavailable_reason"),
                }
            )
            lc = ind.get("local_currency")
            if lc:
                rows.append(
                    {
                        "item": f"{ind['label']} (local currency)",
                        "series_key": ind["series_key"],
                        "state": "ok" if lc.get("yoy_pct") is not None else "unavailable",
                        "yoy_pct": lc.get("yoy_pct"),
                        "baseline_to_peak_pct": lc.get("baseline_to_peak_pct"),
                        "mom_pct": None,
                        "reason": lc.get("yoy_unavailable_reason"),
                    }
                )
        for r in eco["relative_changes"]:
            rows.append(
                {
                    "item": f"{r['label']} ({r['horizon']})",
                    "series_key": r["key"],
                    "state": r["status"],
                    "yoy_pct": r["relative_pct"] if r["horizon"].startswith("12") else None,
                    "baseline_to_peak_pct": None if r["horizon"].startswith("12") else r["relative_pct"],
                    "mom_pct": None,
                    "reason": r["reason"],
                }
            )
        return rows
    if table == "economic_lags":
        return [
            {
                "reference": p["label"],
                "pair": p["key"],
                "lag_months": r["lag"],
                "paired_months": r["n"],
                "spearman": r.get("spearman"),
                "status": r["status"],
                "through": eco["lags"]["through"],
            }
            for p in eco["lags"]["pairs"]
            for r in p["rows"]
        ]
    if table == "economic_lineage":
        keys = (
            "series_key",
            "provider",
            "dataset",
            "concept",
            "label",
            "unit",
            "source_ref",
            "base_period",
            "first_period",
            "last_period",
            "release_lag_months_assumed",
            "vintage_publication_date",
            "retrieved_at",
            "response_sha256",
            "observations_sha256",
            "licence",
            "attribution",
        )
        snap = eco["snapshot"]
        return [
            {"context_snapshot_id": snap["snapshot_id"], "context_observation_hash": snap["observation_hash"]}
            | {k: ln.get(k) for k in keys}
            for ln in eco["lineage"]
        ]
    if table == "economic_notes":
        ev = doc["evidence"].get("economic", {})
        rows = [{"kind": "transformation", "key": k, "text": v} for k, v in eco["transformations"].items()]
        rows += [{"kind": "warning", "key": w["code"], "text": w["text"]} for w in eco["warnings"]]
        rows += [{"kind": "missing", "key": m["key"], "text": f"{m['label']}: {m['reason']}"} for m in eco["missing"]]
        rows += [
            {"kind": "proposition", "key": p["status"], "text": f"{p['proposition']}: {p['verdict']} ({p['basis']})"}
            for p in ev.get("propositions", [])
        ]
        rows += [{"kind": "not_established", "key": c["inference"], "text": c["text"]} for c in ev.get("causal", [])]
        rows.append({"kind": "vintage", "key": "snapshot", "text": eco["snapshot"]["vintage"]})
        rows.append({"kind": "assumption", "key": "release_lags", "text": eco["assumptions"]["note"]})
        return rows
    raise ValueError(f"unknown table {table!r}")


def _cell(v: Any, applies: bool = True) -> str:
    if v is None:
        return "not available" if applies else "—"
    return pct(v)


def economic_markdown(doc: dict[str, Any], table: Any) -> list[str]:
    """The "Economic context" section. ``table`` is the brief's table helper (header, rows) -> lines."""
    sec = doc.get("context", {}).get("economic")
    L: list[str] = ["", "## Economic context", ""]
    if not sec:
        return [*L, "Economic context was not part of this investigation."]
    if sec.get("status") != "ok":
        state = sec.get("state") or sec.get("status")
        return [
            *L,
            f"Economic context is **not available** ({state}): {sec.get('reason') or 'no reason recorded'}.",
            "",
            "Nothing about inflation, exchange rates or international prices is concluded or implied. Their absence "
            "is a gap in the evidence, not evidence that they were unrelated to the price movement.",
        ]
    eco = sec
    snap, w = eco["snapshot"], eco["window"]
    L += [
        f"**Context snapshot:** `{snap['snapshot_id']}` (observation hash `{snap['observation_hash'][:12]}`); "
        f"context identity `{eco['context_id']}`"
        + (f"; information limited to what was assumed published by {month_name(eco['as_of'])}" if eco["as_of"] else "")
        + "  ",
        f"**Vintage:** {snap['vintage']}.  ",
        f"**Window:** {month_name(w['start'])} to {month_name(w['end'])}; month of interest "
        f"{month_name(w['event'])}; pre-episode baseline {month_name(w['baseline_start'])} to "
        f"{month_name(w['baseline_end'])}.",
        "",
    ]
    ev = doc["evidence"].get("economic")
    if ev:
        L += ["### Observed facts", ""] + [f"- {x['text']}" for x in ev["observed"]]
        L += ["", "### Quantitative description", ""] + [f"- {x['text']}" for x in ev["quantitative"]]
        L += ["", "### Propositions the figures can be set beside", ""]
        L += table(
            ["Proposition", "Assessment", "Basis"],
            [[p["proposition"], p["verdict"], p["basis"]] for p in ev["propositions"]],
        )
        L += ["", "### Changes at a glance", ""]
        rows = economic_table_rows(doc, "economic_changes")
        L += table(
            ["Item", "12-month change", "Baseline to peak", "State"],
            [
                [
                    r["item"],
                    _cell(r["yoy_pct"], not (r["item"].startswith("Price relative") and "12-month" not in r["item"])),
                    _cell(
                        r["baseline_to_peak_pct"],
                        not (r["item"].startswith("Price relative") and "12-month" in r["item"]),
                    ),
                    r["state"],
                ]
                for r in rows
            ],
        )
        if eco["warnings"]:
            L += ["", "### Cautions", ""] + [f"- {x['text']}" for x in eco["warnings"]]
        if eco["missing"]:
            L += ["", "### Missing context", ""]
            L += [f"- {m['label']}: **{m['state'].replace('_', ' ')}**. {m['reason']}." for m in eco["missing"]]
        L += ["", "### Not established by this context", ""]
        L += [f"- {x['text']} *({x['inference']})*" for x in ev["causal"]]
        L += ["", "### Unresolved alternatives", ""] + [f"- {x['text']}" for x in ev["unresolved"]]
    L += [
        "",
        "### Sources",
        "",
        "Consumer price indices and exchange rates: International Monetary Fund (IMF), CPI and ER datasets. "
        "International benchmark prices: World Bank Commodity Price Data (the Pink Sheet). Each series' source "
        "reference, vintage, retrieval time and SHA-256 hashes are in the `economic_lineage` CSV table. Percentage "
        "changes are computed by Market Almanac from those series.",
        "",
        "Methods: " + " ".join(f"({i}) {v.rstrip('.')}." for i, v in enumerate(eco["transformations"].values(), 1)),
    ]
    return L
