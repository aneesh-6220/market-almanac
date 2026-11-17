"""Temporal alignment and information-availability rules.

ShockTrace distinguishes four dates (see docs/DATA_DICTIONARY.md):

1. observation period – the month/year a value describes;
2. publication date   – when the source released it (often unknown);
3. retrieval date     – when ShockTrace downloaded it;
4. information cutoff – the latest moment whose information a forecast may use.

When a publication date is unknown, it is **not** replaced by the retrieval date (that would
claim the value was unavailable until we downloaded it – or worse, if the retrieval was
recent, it would be meaningless). Instead a conservative, documented *release lag* is
applied: a value for period ``p`` is treated as usable at forecast origin ``t`` only if
``p + lag <= t``.

All rules here are as-of joins: for each origin month, take the most recent value whose
availability month is <= the origin. No interpolation, no forward-looking fills.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class AvailabilityRule:
    source: str
    frequency: str  # "M" or "A"
    release_lag_months: int  # months after the END of the observation period
    basis: str  # why this lag is used

    def available_from(self, period: pd.Series) -> pd.Series:
        """Month (period start) from which a value becomes usable."""
        p = pd.to_datetime(period)
        if self.frequency == "A":
            # Annual value for year Y ends in December Y; usable from (Dec Y + lag).
            end = p + pd.DateOffset(months=11)
        else:
            end = p
        return (end + pd.DateOffset(months=self.release_lag_months)).dt.to_period("M").dt.to_timestamp()


# Conservative defaults. Publication dates per value are not provided by these sources.
RULES: dict[str, AvailabilityRule] = {
    # WFP monthly prices are collected around mid-month; we assume they are known by the end
    # of the same month and set the forecast origin to that month (lag 0).
    "price": AvailabilityRule("hdx_hapi", "M", 0, "Price for month t is the origin information set at t."),
    # NASA POWER provides near-real-time daily data (days of latency). A completed month t is
    # available at the end of month t.
    "weather": AvailabilityRule("nasa_power", "M", 0, "NRT reanalysis; complete months only."),
    # IMF monthly CPI is typically released 1-2 months after the reference month.
    "imf_cpi": AvailabilityRule("imf", "M", 2, "Conservative 2-month CPI release lag (unknown per-value dates)."),
    "imf_fx": AvailabilityRule("imf", "M", 1, "Conservative 1-month lag for monthly-average exchange rates."),
    # Annual statistics: WDI and FAOSTAT values for year Y are typically released during Y+1.
    "world_bank_annual": AvailabilityRule("world_bank", "A", 12, "Year Y usable from Dec Y+1."),
    "faostat_annual": AvailabilityRule("faostat", "A", 12, "Year Y usable from Dec Y+1 (QCL released ~Dec Y+1)."),
}


def asof_align(
    origins: pd.Series,
    values: pd.DataFrame,
    rule: AvailabilityRule,
    value_col: str = "value",
    published_col: str | None = "published_at",
) -> pd.Series:
    """For each origin month return the latest value usable at that origin.

    ``values`` needs columns ``period`` and ``value_col`` (and optionally a publication
    date). If a real publication date exists it is used (month of publication); otherwise the
    rule's conservative lag applies. Unknown publication dates are never treated as known.
    """
    if values.empty:
        return pd.Series([float("nan")] * len(origins), index=origins.index)
    v = values[["period", value_col] + ([published_col] if published_col and published_col in values else [])].copy()
    v = v.dropna(subset=[value_col])
    avail = rule.available_from(v["period"])
    if published_col and published_col in v.columns:
        pub = pd.to_datetime(v[published_col], utc=True, errors="coerce").dt.tz_localize(None)
        pub_month = pub.dt.to_period("M").dt.to_timestamp()
        # Known publication month wins, but never earlier than the period itself ends.
        period_end = pd.to_datetime(v["period"]) + (
            pd.DateOffset(months=11) if rule.frequency == "A" else pd.DateOffset(0)
        )
        pub_month = pub_month.where(pub_month >= period_end, period_end)
        avail = pub_month.where(pub.notna(), avail)
    v["available_from"] = avail.values
    v = v.sort_values(["available_from", "period"])
    o = pd.DataFrame({"origin": pd.to_datetime(origins).values, "_i": range(len(origins))}).sort_values("origin")
    merged = pd.merge_asof(
        o, v[["available_from", value_col]], left_on="origin", right_on="available_from", direction="backward"
    )
    return pd.Series(merged.sort_values("_i")[value_col].values, index=origins.index)
