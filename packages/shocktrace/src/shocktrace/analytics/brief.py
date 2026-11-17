"""Market intelligence brief: plain-language statements generated from computed evidence.

Every sentence is produced by a fixed template from a number that is also returned in the
``evidence`` block, so the text can always be checked against its source. Templates describe;
they never explain. No sentence states or implies why a price moved.
"""

from __future__ import annotations

from typing import Any

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
LABEL_TEXT = {
    "typical": "within the usual range of past movements for this series",
    "larger_than_usual": "larger than most past movements for this series",
    "unusual": "unusual compared with this series' own history",
    "exceptional": "among the largest movements this series has recorded",
}


def _month(iso: str) -> str:
    y, m = int(iso[:4]), int(iso[5:7])
    return f"{MONTHS[m - 1]} {y}"


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.1f}%"


def _money(v: float, currency: str, unit: str) -> str:
    return f"{v:,.0f} {currency} per {unit}" if v >= 100 else f"{v:,.2f} {currency} per {unit}"


def build_brief(
    meta: dict[str, Any],
    summary: dict[str, Any],
    movement: dict[str, Any],
    quality: dict[str, Any] | None = None,
    peers: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the brief. Inputs are the outputs of the summary, movement and context functions."""
    s: list[dict[str, str]] = []

    def say(section: str, text: str) -> None:
        s.append({"section": section, "text": text})

    name = f"{meta['commodity_name']} in {meta['market_name']} ({meta['country_iso3']})"
    if summary.get("status") != "ok":
        say("what_changed", f"There are no valid price observations for {name}.")
        return {"title": name, "sentences": s, "text": s[0]["text"], "evidence": {"summary": summary}}

    cur, unit = str(meta["currency"]), str(meta["unit"])
    say(
        "latest",
        f"The latest {str(meta['price_type']).lower()} price of {name} is "
        f"{_money(summary['latest_price'], cur, unit)}, observed for {_month(summary['latest_period'])}.",
    )
    behind = summary.get("months_behind_dataset")
    if behind is not None and behind >= 3:
        say(
            "latest",
            f"This series has not been updated for {behind} months relative to the newest price in the dataset, "
            "so it may not reflect current conditions.",
        )
    # what changed / how large / over which period
    if movement.get("status") == "ok":
        span = movement["span_months"]
        over = "the previous month" if span == 1 else f"{_month(movement['reference_period'])} ({span} months earlier)"
        if movement["direction"] == "flat":
            say("what_changed", f"The price is unchanged from {over}.")
        else:
            verb = "rose" if movement["direction"] == "up" else "fell"
            say(
                "what_changed",
                f"It {verb} {_pct(movement['pct_change'])} from {over} "
                f"({_money(movement['reference_price'], cur, unit)}).",
            )
    m12 = (summary.get("changes") or {}).get("m12")
    if m12:
        verb = "higher" if m12["pct_change"] > 0 else "lower" if m12["pct_change"] < 0 else "unchanged"
        say(
            "what_changed",
            f"Compared with {_month(m12['reference_period'])} it is "
            + (f"{_pct(m12['pct_change'])} {verb}." if verb != "unchanged" else "unchanged."),
        )
    # is it unusual
    label = movement.get("label", "insufficient_history")
    ov = movement.get("overall") or {}
    if label in LABEL_TEXT and movement.get("direction") == "flat":
        say(
            "unusualness",
            f"The price did not change, which is {LABEL_TEXT[label]} "
            f"({ov.get('n_reference', 0)} earlier comparable changes).",
        )
    elif label in LABEL_TEXT and ov.get("percentile_of_size") is not None:
        say(
            "unusualness",
            f"The latest movement is {LABEL_TEXT[label]}: it is larger than "
            f"{ov['percentile_of_size'] * 100:.0f}% of the {ov['n_reference']} earlier comparable changes"
            + ("." if movement.get("stable") else "; with this little history the assessment may be unstable."),
        )
        seas = movement.get("seasonal")
        if seas and seas.get("percentile_of_size") is not None:
            say(
                "unusualness",
                f"Against earlier changes ending in {MONTHS[seas['calendar_month'] - 1]} it is larger than "
                f"{seas['percentile_of_size'] * 100:.0f}% of {seas['n_reference']} years.",
            )
    else:
        say(
            "unusualness",
            "There is not enough history to say whether the latest movement is unusual"
            + (f" ({ov.get('n_reference', 0)} earlier comparable changes)." if ov else "."),
        )
    for w in movement.get("warnings", []):
        if "spans" in w:
            say("unusualness", w[0].upper() + w[1:] + ".")
    vol = movement.get("volatility")
    if vol and vol.get("label") == "elevated":
        say(
            "unusualness",
            f"Month-to-month variability over the last {vol['window_months']} months is higher than in "
            f"{vol['percentile'] * 100:.0f}% of earlier periods.",
        )
    if peers and peers.get("status") == "ok":
        share = peers["share_same_direction"] * 100
        say(
            "unusualness",
            f"In the same month {share:.0f}% of the {peers['n_peers']} other markets reporting this commodity in the "
            f"country moved in the same direction (median change {peers['peer_median_pct_change'] * 100:+.1f}%).",
        )
        if peers["pattern"] == "isolated_reversing":
            say(
                "unusualness",
                "The movement was not shared by other markets and reversed the following month, a pattern that can "
                "indicate a reporting or measurement anomaly rather than a market movement.",
            )
    # data completeness
    say(
        "data",
        f"The series has {summary['n_observations']} monthly observations from {_month(summary['first_period'])} "
        f"({summary['coverage'] * 100:.0f}% of months observed); {summary['missing_months_last_24']} of the last 24 "
        "months are missing.",
    )
    if quality:
        if quality.get("eligible"):
            say("data", "It meets ShockTrace's completeness rules for forecast evaluation.")
        else:
            say(
                "data",
                "It does not meet the completeness rules for forecast evaluation ("
                + "; ".join(quality.get("reasons", [])[:2])
                + ").",
            )
    # environment
    if environment and environment.get("status") == "ok":
        loc = environment.get("market_cell")
        if loc and loc.get("rain_anomaly_z") is not None:
            z = loc["rain_anomaly_z"]
            word = "close to" if abs(z) < 0.5 else "above" if z > 0 else "below"
            say(
                "environment",
                f"Rainfall at the market's grid cell in {_month(loc['period'])} was {word} the average of earlier "
                f"years for that month (standardised anomaly {z:+.1f})."
                + (" That month's source data carried a quality flag." if loc.get("qc_flagged") else ""),
            )
        prod = environment.get("production_region")
        if prod and prod.get("season_rain_anomaly_z") is not None:
            z = prod["season_rain_anomaly_z"]
            word = "close to" if abs(z) < 0.5 else "above" if z > 0 else "below"
            state = "so far" if prod.get("in_season") else "overall"
            say(
                "environment",
                f"Across the country's {prod['crop']}-growing areas, seasonal rainfall {state} was {word} that of "
                f"earlier seasons at the same stage (standardised anomaly {z:+.1f}, as of {_month(prod['period'])}).",
            )
        say(
            "environment",
            "Weather is shown as context only. ShockTrace's out-of-sample tests have not established that these "
            "measurements improve price forecasts, and they do not identify causes.",
        )
    else:
        say("environment", "No weather context is stored for this market.")
    # forecast
    if forecast and forecast.get("status") == "issued":
        v = forecast.get("validation_status")
        qualifier = (
            "its model beat the no-change benchmark out of sample"
            if v == "validated_outperforms_baseline"
            else "its model did not beat the no-change benchmark out of sample, so it carries no demonstrated skill"
        )
        say(
            "forecast",
            f"A statistical forecast for {_month(forecast['target_period'])} exists; {qualifier}. "
            "It rests on an assumed data-availability scenario, not verified real-time information.",
        )
    elif forecast and forecast.get("status") == "withheld":
        say("forecast", f"No forecast is shown for this series: {forecast.get('reason', 'it did not qualify')}.")
    else:
        say("forecast", "No evaluated forecasting model covers this series, so no forecast is shown.")
    say(
        "uncertainty",
        "Prices are monthly market reports collected by WFP and partners; they can be revised, and a single "
        "market may not represent a wider area. Statements here describe the data and do not explain causes.",
    )
    return {
        "title": name,
        "as_of_period": summary["latest_period"],
        "sentences": s,
        "text": " ".join(x["text"] for x in s),
        "evidence": {
            "summary": summary,
            "movement": movement,
            "peers": peers,
            "environment": environment,
            "forecast": forecast,
            "quality": quality,
        },
        "method": "Deterministic templates over computed statistics; no language model and no causal inference.",
    }
