"""Deterministic evidence statements for the economic-context section of a price-shock investigation.

This extends :mod:`market_almanac.analytics.evidence` without changing it for investigations that have no economic
context: :func:`apply` is called only when ``doc["context"]["economic"]`` has usable data, adds an ``economic`` block to
the evidence, and replaces the evidence and status of the two existing mechanisms the context can speak to (general
inflation or currency, and transmission of international prices).

The same seven layers as the rest of the evidence system, kept apart:

* **observed**: which series exist, what the sources publish and what they do not;
* **quantitative**: changes, relative changes, exact decompositions and lagged correlations (descriptive arithmetic);
* **consistent**: statements that a pattern is consistent with a mechanism (never "caused by");
* **propositions**: named claims a reader might make, each marked consistent, partly consistent, argued against
  (by the numbers shown) or not assessable;
* **unresolved**: alternatives the integrated data cannot separate;
* **gaps**: what is missing, from the explicit missing states and what the sources do not provide;
* **causal**: interpretations that would need causal identification and are therefore *not* supported.

No language model is involved. Wording avoids causal verbs outside the last layer, which names them in order to
disclaim them (a test enforces this).
"""

from __future__ import annotations

from typing import Any

from market_almanac.analytics.evidence import STATUS_TEXT, _st, month_name, pct
from market_almanac.context import transforms as T

SHARE_CONSISTENT = 0.5
SHARE_PARTIAL = 0.2
MATERIAL = T.MATERIAL_CHANGE
CAUSAL_WORDS = (
    "caused",
    "because of",
    "due to",
    "drove",
    "driven by",
    "led to",
    "resulted in",
    "explains",
    "is responsible",
)


def _ok(ind: dict[str, Any] | None) -> bool:
    return ind is not None and ind.get("state") == "ok" and ind.get("yoy_pct") is not None


def _share_status(part: float | None, whole: float | None, up: bool) -> tuple[str, float | None]:
    """How much of the price's 12-month log change another change accounts for, as a status. Arithmetic, not cause."""
    if part is None or whole is None or not up or whole < MATERIAL:
        return "cannot_be_assessed", None
    share = T.log_share(part, whole)
    if share is None:
        return "cannot_be_assessed", None
    if share >= SHARE_CONSISTENT:
        return "consistent", share
    if share >= SHARE_PARTIAL:
        return "partly_consistent", share
    return "less_likely", share


def _status_for_share(share: float) -> str:
    if share >= SHARE_CONSISTENT:
        return "consistent"
    return "partly_consistent" if share >= SHARE_PARTIAL else "less_likely"


def _combine(statuses: list[str]) -> str:
    real = [s for s in statuses if s != "cannot_be_assessed"]
    if not real:
        return "cannot_be_assessed"
    for s in ("consistent", "partly_consistent"):
        if s in real:
            return s
    return "less_likely" if all(s == "less_likely" for s in real) else "context_only"


def apply(doc: dict[str, Any], mechanisms: list[dict[str, Any]]) -> dict[str, Any] | None:
    eco = doc["context"].get("economic")
    if not eco or eco.get("status") != "ok":
        return None
    s = doc["subject"]
    up = doc["direction"] == "up"
    ev = month_name(eco["window"]["event"])
    country = s["country_name"]
    price_yoy = eco["price"]["yoy_pct"]
    infl, fx, intl = eco["inflation"], eco["exchange_rate"], eco["international"]
    head, food = infl["headline"], infl["food"]
    pa = fx["period_average"] if fx["period_average"]["state"] == "ok" else fx["end_period"]
    vintage = f"IMF/World Bank snapshot {eco['snapshot']['snapshot_id']}"

    observed: list[dict[str, Any]] = []
    quant: list[dict[str, Any]] = []
    consistent: list[dict[str, Any]] = []
    props: list[dict[str, Any]] = []

    # ---- observed -------------------------------------------------------------------------------------------------
    for ind, name in (
        (head, "headline consumer price index"),
        (food, "food consumer price index"),
        (pa, "exchange rate"),
    ):
        if ind["state"] == "ok":
            c = ind["coverage"]
            observed.append(
                _st(
                    f"The IMF {name} for {country} is available from {month_name(c['first_period'])} to "
                    f"{month_name(c['last_period'])} ({c['n_obs']} months; {c['months_missing_in_window']} of "
                    f"{c['months_in_window']} window months missing).",
                    keys=[ind["series_key"]],
                )
            )
        else:
            observed.append(_st(f"No usable IMF {name} for {country}: {ind['reason']}.", keys=[ind["series_key"]]))
    if intl.get("items"):
        names = ", ".join(i["label"] for i in intl["items"])
        observed.append(
            _st(
                f"{s['commodity_name']} is mapped to {names} with {intl['confidence']} confidence "
                f"({intl.get('role') or 'role not stated'}). {intl['confidence_text']}",
                keys=["context.economic.international"],
            )
        )
    else:
        observed.append(
            _st(
                f"No international benchmark is mapped to {s['commodity_name']}: {intl.get('reason')}",
                keys=["context.economic.international"],
            )
        )
    for w in eco["warnings"]:
        if w["severity"] == "warn":
            observed.append(_st(w["text"], keys=["context.economic.warnings"]))

    # ---- quantitative ---------------------------------------------------------------------------------------------
    if price_yoy is not None:
        quant.append(
            _st(
                f"The local price changed {pct(price_yoy)} over the 12 months to {ev} (nominal, {s['currency']}).",
                keys=["context.economic.price"],
            )
        )
    if _ok(head):
        quant.append(
            _st(
                f"The national consumer price index changed {pct(head['yoy_pct'])} over the same 12 months "
                f"({vintage}). A change in one food's price and the change in the general price level are "
                "different quantities.",
                keys=[head["series_key"]],
            )
        )
    if _ok(food):
        quant.append(
            _st(
                f"The food component of the consumer price index changed {pct(food['yoy_pct'])}.",
                keys=[food["series_key"]],
            )
        )
        if infl.get("food_minus_headline_yoy_pp") is not None:
            quant.append(
                _st(
                    f"Food inflation exceeded headline inflation by {infl['food_minus_headline_yoy_pp']:+.1f} "
                    "percentage points.",
                    keys=["context.economic.inflation"],
                )
            )
    for r in eco["relative_changes"]:
        if r["status"] == "ok":
            quant.append(
                _st(
                    f"{r['label']} ({r['horizon']}): the price changed {pct(r['nominal_pct'])} against "
                    f"{pct(r['deflator_pct'])} for the {r['deflator']}, a relative change of {pct(r['relative_pct'])}. "
                    "This is the price relative to "
                    "the national average basket, not a change in any household's purchasing power.",
                    keys=["context.economic.relative_changes"],
                )
            )
        elif r["horizon"].startswith("12"):
            quant.append(
                _st(f"{r['label']} cannot be computed: {r['reason']}.", keys=["context.economic.relative_changes"])
            )
    if _ok(pa):
        usd_v = pa.get("usd_value_change_yoy_pct")
        basis_name = "period average" if pa is fx["period_average"] else "end of period"
        moved = round(pa["yoy_pct"] * 100, 1) != 0
        direction = (
            f" ({'more' if pa['yoy_pct'] > 0 else 'fewer'} units per dollar)"
            if moved
            else " (the official rate did not move)"
        )
        quant.append(
            _st(
                f"Domestic currency per US dollar changed {pct(pa['yoy_pct'])} over the 12 months{direction}, a "
                f"{pct(usd_v)} change in the dollar value of one unit of the local currency (official rate, "
                f"{basis_name}).",
                keys=[pa["series_key"]],
            )
        )
        if fx.get("average_vs_end_period_yoy_pp") is not None and abs(fx["average_vs_end_period_yoy_pp"]) >= 1:
            quant.append(
                _st(
                    f"The end-of-period rate changed {fx['average_vs_end_period_yoy_pp']:+.1f} percentage points "
                    "differently from the period average, so the two conventions tell different stories here.",
                    keys=["context.economic.exchange_rate"],
                )
            )
    if eco.get("usd_price") and eco["usd_price"]["yoy_pct"] is not None:
        diverged = any(w["code"] == "official_rate_caution" for w in eco["warnings"])
        quant.append(
            _st(
                f"At the official period-average rate the price in US dollars changed "
                f"{pct(eco['usd_price']['yoy_pct'])}"
                + (
                    " (official rates in this country have diverged from market rates, so this may be far from the "
                    "dollar price households faced)."
                    if diverged
                    else " (indicative; households may have faced a different rate)."
                ),
                keys=["context.economic.usd_price"],
            )
        )
    for it in intl.get("items", []):
        if it["state"] != "ok":
            quant.append(_st(f"{it['label']}: not usable ({it['reason']}).", keys=[it["series_key"]]))
            continue
        if it.get("yoy_pct") is not None:
            quant.append(
                _st(
                    f"{it['label']} changed {pct(it['yoy_pct'])} in US dollars over the 12 months to {ev}.",
                    keys=[it["series_key"]],
                )
            )
        else:
            quant.append(
                _st(
                    f"The 12-month change of {it['label']} cannot be computed: {it['yoy_unavailable_reason']}.",
                    keys=[it["series_key"]],
                )
            )
        lc = it.get("local_currency")
        if lc and lc.get("decomposition_yoy"):
            d = lc["decomposition_yoy"]
            quant.append(
                _st(
                    f"In local currency the same benchmark changed {pct(d['local_currency_change'])}: a "
                    f"{pct(it['yoy_pct'])} change in dollars combined with a {pct(pa['yoy_pct'])} change in the "
                    f"exchange "
                    f"rate "
                    f"(log changes {d['usd_benchmark_log']:+.3f} and {d['exchange_rate_log']:+.3f}, adding exactly). "
                    "The split is arithmetic and does not show why either part moved.",
                    keys=[it["series_key"]],
                )
            )
            share = _share_status(d["local_currency_change"], price_yoy, up)[1]
            if share is not None:
                quant.append(
                    _st(
                        f"The benchmark's local-currency change is {share:.0%} of the price's 12-month log change "
                        "(arithmetic ratio of two logarithmic changes).",
                        keys=[it["series_key"]],
                    )
                )
    for pair in eco["lags"]["pairs"]:
        rows = [r for r in pair["rows"] if r["status"] == "ok"]
        if rows:
            lo, hi = min(r["spearman"] for r in rows), max(r["spearman"] for r in rows)
            quant.append(
                _st(
                    f"Rank correlations between monthly changes in this price and {pair['label']} led by 0 to 6 months "
                    f"ranged "
                    f"from {lo:+.2f} to {hi:+.2f} (up to {max(r['n'] for r in rows)} paired months through "
                    f"{month_name(eco['lags']['through'])}). Descriptive; no lag is singled out.",
                    "associational",
                    keys=["context.economic.lags"],
                )
            )
        elif any(r["status"] == "no_variation" for r in pair["rows"]):
            quant.append(
                _st(
                    f"Monthly changes of {pair['label']} take too few distinct values in the overlapping months "
                    f"({pair['n_pairs_lag0']}) for a rank correlation to be defined (for example an administered rate "
                    "that did not move).",
                    keys=["context.economic.lags"],
                )
            )
        else:
            quant.append(
                _st(
                    f"Too few overlapping months (at most {pair['n_pairs_lag0']}, 24 needed) to compare monthly "
                    f"changes with {pair['label']}.",
                    keys=["context.economic.lags"],
                )
            )

    # ---- propositions and consistency -----------------------------------------------------------------------------
    def prop(text: str, status: str, basis: str, keys: list[str]) -> str:
        verdict = {
            "consistent": "consistent",
            "partly_consistent": "partly consistent",
            "less_likely": "argued against by these figures",
            "cannot_be_assessed": "not assessable",
            "context_only": "context only",
        }[status]
        props.append({"proposition": text, "status": status, "verdict": verdict, "basis": basis, "evidence": keys})
        return status

    st_head = "cannot_be_assessed"
    if _ok(head):
        st_head, sh = _share_status(head["yoy_pct"], price_yoy, up)
        if sh is None:
            basis = "the price's 12-month change is too small, or not a rise, for a share to be meaningful"
        else:
            basis = (
                f"the national consumer price index changed {pct(head['yoy_pct'])} against {pct(price_yoy)} for this "
                f"price, {sh:.0%} of its log change. The index is a national average of a different basket, so a "
                "small figure does not exclude a local or product-specific price-level movement"
            )
        prop(
            "General inflation, as measured by the national consumer price index, accounts for most of the rise",
            st_head,
            basis,
            [head["series_key"]],
        )
    else:
        prop(
            "General inflation, as measured by the national consumer price index, accounts for most of the rise",
            "cannot_be_assessed",
            f"no usable headline index: {head['reason'] or head.get('yoy_unavailable_reason')}",
            [head["series_key"]],
        )
    st_food = "cannot_be_assessed"
    if _ok(food):
        st_food, sh = _share_status(food["yoy_pct"], price_yoy, up)
        prop(
            "Food inflation, as measured by the food component of the index, accounts for most of the rise",
            st_food,
            f"food CPI changed {pct(food['yoy_pct'])} against {pct(price_yoy)} for this price"
            + (f" ({sh:.0%} of its log change)" if sh is not None else ""),
            [food["series_key"]],
        )
    else:
        prop(
            "Food inflation, as measured by the food component of the index, accounts for most of the rise",
            "cannot_be_assessed",
            f"no usable food index: {food['reason'] or food.get('yoy_unavailable_reason')}",
            [food["series_key"]],
        )
    st_fx = "cannot_be_assessed"
    fx_text = "A depreciation of the local currency against the US dollar accounts for most of the rise"
    if fx["applicability"] == "applies" and _ok(pa):
        st_fx, sh = _share_status(pa["yoy_pct"], price_yoy, up)
        basis = (
            f"units of local currency per dollar changed {pct(pa['yoy_pct'])} against {pct(price_yoy)} for the price"
            + (f" ({sh:.0%} of its log change)" if sh is not None else "")
        )
        if fx["regime"] and fx["regime"][0]["kind"] in ("currency_union_peg", "peg"):
            basis += (
                f". The currency is pegged ({fx['regime'][0]['currency']} to {fx['regime'][0]['anchor']}), so this "
                "movement mirrors the anchor currency's value against the dollar"
            )
        if any(w["code"] == "official_rate_caution" for w in eco["warnings"]):
            basis += (
                ". Official rates in this country have diverged from market rates, so the figure may not describe "
                "the rate importers faced"
            )
            if st_fx == "less_likely":
                st_fx = (
                    "context_only"  # an official rate that may not describe the transaction rate cannot argue against
                )
        prop(fx_text, st_fx, basis, [pa["series_key"]])
    else:
        why = {
            "price_in_usd": "the price is recorded in US dollars",
            "dollarized": "the economy uses the US dollar",
            "currency_mismatch": "the price currency differs from the national currency of the exchange-rate series",
            "no_series": "no exchange-rate series is integrated for this country",
        }.get(fx["applicability"], "no usable exchange rate")
        prop(fx_text, "cannot_be_assessed", why, [])
    st_int = "cannot_be_assessed"
    int_text = "International benchmark prices, in local currency, moved by a comparable amount to this price"
    usable = [
        i
        for i in intl.get("items", [])
        if i["state"] == "ok" and (i.get("local_currency") or {}).get("yoy_pct") is not None
    ]
    if usable and intl["confidence"] == "medium":
        sts = [_share_status(i["local_currency"]["yoy_pct"], price_yoy, up) for i in usable]
        shares = sorted(sh for _, sh in sts if sh is not None)
        if shares:
            mid = len(shares) // 2
            median = shares[mid] if len(shares) % 2 else (shares[mid - 1] + shares[mid]) / 2
            st_int = _status_for_share(median)
            spread = (
                f"; the share of the price's log change is {median:.0%} at the median across "
                f"{len(shares)} benchmark{'s' if len(shares) > 1 else ''} (range {shares[0]:.0%} to "
                f"{shares[-1]:.0%}). The median is used so that the most favourable of several alternative "
                "quotations does not decide the status"
            )
        else:
            st_int, spread = "cannot_be_assessed", "; the price's 12-month change is too small, or not a rise"
        basis = "; ".join(
            f"{i['label']} changed {pct(i['local_currency']['yoy_pct'])} in local currency" for i in usable
        )
        prop(
            int_text,
            st_int,
            basis + f" against {pct(price_yoy)} for this price" + spread + ". Grade, place, freight, duties and "
            "margins differ between the benchmark and the local product",
            [i["series_key"] for i in usable],
        )
    elif usable:
        st_int = "context_only"
        prop(
            int_text,
            "context_only",
            f"the mapping is rated {intl['confidence']}: a similar movement would be weak "
            "evidence and a different one would not argue against anything",
            [i["series_key"] for i in usable],
        )
    else:
        prop(
            int_text,
            "cannot_be_assessed",
            intl.get("reason") or "no usable benchmark series with a local-currency change",
            [],
        )

    for p in props:
        if p["status"] == "consistent":
            lead = "The figures are consistent with this"
        elif p["status"] == "partly_consistent":
            lead = (
                "The figures are only partly consistent with this: they fit it accounting for part of the rise, "
                "not most of it. Proposition"
            )
        else:
            continue
        consistent.append(
            _st(f"{lead}: {p['proposition'].lower()} ({p['basis']}).", "associational", keys=p["evidence"])
        )

    # ---- mechanisms (replace the two the context can speak to) ----------------------------------------------------
    macro = _combine([st_head, st_food, st_fx])
    for m in mechanisms:
        if m["key"] == "macro":
            items = [f"{p['proposition']}: {p['verdict']} ({p['basis']})" for p in props[:3]]
            _set(
                m,
                macro,
                items,
                [
                    "a parallel-market or import-cost exchange rate where the official rate diverged (not integrated)",
                    "import prices, tariffs and freight for the commodity (not integrated)",
                ],
            )
        elif m["key"] == "international":
            items = [f"{props[3]['proposition']}: {props[3]['verdict']} ({props[3]['basis']})"]
            _set(
                m,
                st_int,
                items,
                [
                    "the commodity's actual origin, grade and landed cost (not integrated)",
                    "import dependence and trade policy for the country (not integrated)",
                ],
            )

    # ---- unresolved, gaps, causal ---------------------------------------------------------------------------------
    unresolved = [
        _st(
            "Local supply conditions (harvest, stocks), transport and border costs, trade and price policy, "
            "conflict and access, demand shifts and recording changes can each coincide with the movements "
            "shown above; the "
            "integrated data cannot separate them.",
            keys=["context.economic"],
        )
    ]
    gaps: list[str] = []
    for mset in eco["missing"]:
        gaps.append(f"{mset['label']}: {mset['reason']}")
    gaps += [
        "sub-national consumer price indices (the IMF series are national averages)",
        "the exchange rate actually faced by importers and traders, where it differs from the official rate",
    ]
    causal = [
        _st(
            "That inflation, depreciation or an international price caused the local price movement. The "
            "context places magnitudes side by side; attributing the movement to any of them requires a design "
            "that separates it "
            "from the others, which move together.",
            "causal",
        ),
        _st(
            "That a lead-lag pattern in monthly changes shows transmission from a benchmark, a currency or an index. "
            "Seven lags are examined and monthly changes are autocorrelated.",
            "causal",
        ),
        _st(
            "That a benchmark's path describes the cost of the product sold locally. A world export quotation differs "
            "from the local product in grade, place, stage of the chain and currency.",
            "causal",
        ),
        _st("That a relative price change is a change in households' purchasing power or welfare.", "causal"),
    ]
    return {
        "format": eco["format"],
        "context_id": eco["context_id"],
        "observed": observed,
        "quantitative": quant,
        "consistent": consistent,
        "propositions": props,
        "unresolved": unresolved,
        "gaps": gaps,
        "causal": causal,
        "statuses": {k: STATUS_TEXT[k] for k in STATUS_TEXT},
    }


def _set(m: dict[str, Any], status: str, evidence: list[str], needed: list[str]) -> None:
    m["status"] = status
    m["status_text"] = STATUS_TEXT[status]
    m["evidence"] = evidence
    m["needed"] = needed
    m.pop("evidence_groups", None)
    m["source"] = "economic_context"


def causal_language(statements: list[dict[str, Any]]) -> list[str]:
    """Texts in ``statements`` that contain a causal verb (used by the tests; empty for every layer but ``causal``)."""
    return [x["text"] for x in statements if any(w in x["text"].lower() for w in CAUSAL_WORDS)]
