"""The Sahel production-region weather study (protocol: docs/research/RESEARCH_PROTOCOL.md).

Question. Does weather measured over crop-production regions and aligned with the growing
season improve out-of-sample food-price forecasts beyond (a) price history and (b) weather
measured at the retail market?

Everything that defines the study is in ``STUDY`` below and in the protocol document; both were
committed and tagged before any model was estimated on the confirmatory countries. This module
only orchestrates: it runs one experiment per country, crop and variant with the ordinary
engine, then pools matched predictions across a country's crops for the confirmatory tests.

Variants per (country, crop), all with families A, B, P on identical rows:

    primary        price lag L = 1, QC'd precipitation
    lag0, lag2     price lag 0 and 2 (timing sensitivity)
    rawprecip      L = 1 with raw source precipitation (QC sensitivity)
    placebo_shift  L = 1, production features taken from 60 months earlier (falsification)
    placebo_crop   L = 1, production features built with another crop's weights and calendar
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from shocktrace.config import Settings
from shocktrace.evaluation.backtest import common_sample
from shocktrace.evaluation.inference import holm_adjust
from shocktrace.experiments.config import ExperimentConfig
from shocktrace.experiments.runner import ExperimentOutput, _compare, clean_for_json
from shocktrace.features.production_weather import build_production_features
from shocktrace.features.weather import ClimatologyConfig
from shocktrace.geo.spam import crop_for_commodity, packaged_weights
from shocktrace.services import load_datasets, run_and_register, store_for

PLACEBO_SHIFT_MONTHS = 60
WRONG_CROP = {"millet": "maize", "maize": "millet", "sorghum": "cowpea", "cowpea": "sorghum"}
MIN_NATIONAL_AREA_HA = 100_000.0  # a crop must be grown at scale for a production-region proxy to be meaningful


@dataclass(frozen=True)
class StudySpec:
    study_id: str
    horizons: tuple[int, ...]
    primary_lag: int
    sensitivity_lags: tuple[int, ...]
    alpha: float
    # country -> commodity codes, by evidence class
    exploratory: dict[str, tuple[str, ...]]
    confirmatory: dict[str, tuple[str, ...]]
    secondary: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def cells(self, phase: str) -> list[tuple[str, str, str]]:
        """(country, commodity_code, evidence_class) for a phase: exploratory | confirmatory | all."""
        out: list[tuple[str, str, str]] = []
        if phase in ("exploratory", "all"):
            out += [(c, k, "exploratory") for c, ks in self.exploratory.items() for k in ks]
        if phase in ("confirmatory", "all"):
            out += [(c, k, "confirmatory") for c, ks in self.confirmatory.items() for k in ks]
            out += [(c, k, "exploratory") for c, ks in self.secondary.items() for k in ks]
        return out


STUDY = StudySpec(
    study_id="sahel-production-weather-v1",
    horizons=(1, 3),
    primary_lag=1,
    sensitivity_lags=(0, 2),
    alpha=0.05,
    # Burkina Faso's 2021-2026 test period shaped v0.1 of the method: exploratory only.
    exploratory={"BFA": ("73", "135", "67", "120")},
    # Mali and Niger: no model had been estimated on them before the protocol was frozen.
    confirmatory={"MLI": ("73", "65", "51", "120"), "NER": ("73", "65")},
    # Niger maize: 7,437 ha in MapSPAM 2010, far below the scale threshold; reported, not confirmatory.
    secondary={"NER": ("51",)},
)

VARIANTS = ("primary", "lag0", "lag2", "rawprecip", "placebo_shift", "placebo_crop")
CONTRASTS = (("ridge_A", "ridge_P", "P_vs_A"), ("ridge_B", "ridge_P", "P_vs_B"), ("ridge_A", "ridge_B", "B_vs_A"))
CONFIRMATORY_CONTRASTS = ("P_vs_A", "P_vs_B")


def experiment_id(spec: StudySpec, country: str, commodity: str, variant: str) -> str:
    return f"{spec.study_id.replace('-', '_')}_{country}_{commodity}_{variant}"[:64]


def variant_config(
    spec: StudySpec, country: str, commodity: str, name: str, evidence_class: str, variant: str
) -> ExperimentConfig:
    lag = {"lag0": 0, "lag2": 2}.get(variant, spec.primary_lag)
    return ExperimentConfig(
        name=f"{name} [{variant}]" if variant != "primary" else name,
        country_iso3=country,
        commodity_codes=[commodity],
        horizons=list(spec.horizons),
        families=["A", "B", "P"],
        include_trees=False,
        sensitivity_thresholds=[0.10],
        price_release_lag_months=lag,
        weather_release_lag_months=0,
        use_precip_qc=variant != "rawprecip",
        # only the primary variant on a confirmatory cell is confirmatory evidence
        evidence_class=evidence_class if variant == "primary" else "exploratory",
        study=spec.study_id,
        variant=variant,
    )


def placebo_features(
    variant: str, weather: pd.DataFrame, country: str, commodity: str, commodity_name: str
) -> pd.DataFrame | None:
    """Production features for a falsification variant (None for ordinary variants)."""
    clim = ClimatologyConfig()
    if variant == "placebo_shift":
        f, _ = build_production_features(weather, country, {commodity: commodity_name}, clim)
        weather_cols = [c for c in f.columns if c.endswith("_anom") or c.endswith("_anom_prev")]
        g = f.sort_values("period").copy()
        # same calendar month five years earlier: keeps seasonality and the calendar indicators,
        # removes any information about the current season, and uses no future data
        g[weather_cols] = g[weather_cols].shift(PLACEBO_SHIFT_MONTHS)
        return g
    if variant == "placebo_crop":
        crop = crop_for_commodity(commodity_name)
        other = WRONG_CROP.get(crop or "")
        if other is None:
            return None
        f, _ = build_production_features(
            weather, country, {commodity: commodity_name}, clim, crop_override={commodity: other}
        )
        return f
    return None


def _regression_sample(out: ExperimentOutput, h: int, models: list[str]) -> pd.DataFrame:
    p = out.predictions
    if p.empty:
        return p
    p = p[(p["task"] == "regression") & (p["horizon"] == h)]
    return common_sample(p, models)


def _row_meta(outs: list[ExperimentOutput]) -> pd.DataFrame | None:
    frames = [
        o.panel.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])[
            ["location_id", "w_qc_flag"]
        ]
        for o in outs
        if o.panel is not None
    ]
    return pd.concat(frames) if frames else None


def pooled_contrast(
    outs: list[ExperimentOutput], a: str, b: str, h: int, cfg: ExperimentConfig, role: str
) -> dict[str, Any] | None:
    """One comparison on the rows of all given experiments, matched across ridge A, B and P.

    The loss differential is averaged over every series (all crops) within an origin month
    before the Diebold-Mariano test, so cross-market and cross-crop dependence within a month
    is absorbed and the effective sample is the number of months.
    """
    samples = [_regression_sample(o, h, ["ridge_A", "ridge_B", "ridge_P"]) for o in outs]
    samples = [s for s in samples if not s.empty]
    if not samples:
        return None
    c = _compare(pd.concat(samples, ignore_index=True), a, b, "regression", h, cfg, role, _row_meta(outs))
    c["n_series"] = int(sum(s["series_id"].nunique() for s in samples))
    c["n_experiments"] = len(samples)
    return c


def placebo_contrast(
    real: list[ExperimentOutput], fake: list[ExperimentOutput], h: int, cfg: ExperimentConfig, role: str
) -> dict[str, Any] | None:
    """Real production features versus a falsification variant, on rows both runs predicted."""
    frames = []
    for r, f in zip(real, fake, strict=True):
        a = _regression_sample(r, h, ["ridge_P"])
        b = _regression_sample(f, h, ["ridge_P"]).assign(model="ridge_P_placebo")
        if a.empty or b.empty:
            continue
        frames.append(pd.concat([a, b], ignore_index=True))
    if not frames:
        return None
    both = common_sample(pd.concat(frames, ignore_index=True), ["ridge_P", "ridge_P_placebo"])
    if both.empty:
        return None
    return _compare(both, "ridge_P_placebo", "ridge_P", "regression", h, cfg, role)


def _slim(c: dict[str, Any] | None) -> dict[str, Any] | None:
    """The fields of a comparison that the study tables report."""
    if c is None:
        return None
    infl = c.get("influence") or {}
    return {
        "model_a": c["model_a"],
        "model_b": c["model_b"],
        "horizon": c["horizon"],
        "n_rows": c["n_rows"],
        "n_series": c.get("n_series"),
        "n_months": c["dm"]["n_periods"],
        "loss_ratio": c["relative_loss_b_vs_a"],
        "loss_ratio_monthly": c["bootstrap_loss_ratio"]["ratio"],
        "ci_low": c["bootstrap_loss_ratio"]["ci_low"],
        "ci_high": c["bootstrap_loss_ratio"]["ci_high"],
        "mean_loss_a": c["mean_loss_a"],
        "mean_loss_b": c["mean_loss_b"],
        "dm_stat": c["dm"]["stat"],
        "p_b_better": c["dm"]["p_value_b_better"],
        "p_two_sided": c["dm"]["p_value_two_sided"],
        "subperiod_mean_diff": [hh["mean_diff"] for hh in c["subperiods"]],
        "verdict": c["verdict"],
        "fragile": infl.get("fragile"),
        "fragility_reasons": infl.get("reasons"),
        "ratio_without_top3_months": (infl.get("months") or {}).get("ratio_without_top_k"),
        "top_months": [(m["origin"], round(m["shift"], 4)) for m in (infl.get("months") or {}).get("top", [])],
    }


def run_study(
    settings: Settings,
    phase: str = "all",
    spec: StudySpec = STUDY,
    variants: tuple[str, ...] = VARIANTS,
    progress: Any = None,
) -> dict[str, Any]:
    """Run the study phase and return the pooled results (also written under the experiments dir)."""
    if phase not in ("exploratory", "confirmatory", "all"):
        raise ValueError("phase must be exploratory, confirmatory or all")
    store = store_for(settings)
    loaded = load_datasets(store)
    data, snaps = loaded
    prices, weather = data["prices"], data["weather_monthly"]
    weights = packaged_weights()
    names = prices.drop_duplicates(["country_iso3", "commodity_code"]).set_index(["country_iso3", "commodity_code"])[
        "commodity_name"
    ]
    runs: dict[tuple[str, str, str], ExperimentOutput] = {}
    index: list[dict[str, Any]] = []
    for country, commodity, evidence in spec.cells(phase):
        cname = str(names[(country, commodity)])
        crop = crop_for_commodity(cname)
        area = float(weights[(weights["country_iso3"] == country) & (weights["crop"] == crop)]["area_ha"].sum())
        for variant in variants:
            cfg = variant_config(spec, country, commodity, f"{country}: {cname}", evidence, variant)
            extra = None
            if variant.startswith("placebo"):
                pf = placebo_features(variant, weather, country, commodity, cname)
                if pf is None:
                    continue
                extra = {"production_features": pf}
            eid = experiment_id(spec, country, commodity, variant)
            if progress:
                progress(f"{eid}")
            out = run_and_register(settings, cfg, eid, loaded=loaded, extra_datasets=extra)
            runs[(country, commodity, variant)] = out
            index.append(
                {
                    "experiment_id": eid,
                    "country": country,
                    "commodity_code": commodity,
                    "commodity_name": cname,
                    "crop": crop,
                    "variant": variant,
                    "evidence_class": cfg.evidence_class,
                    "n_series": len(out.results.get("eligible_series", [])),
                    "spam_area_kept_ha": area,
                    "status": out.results.get("status"),
                }
            )
    results = summarise(spec, phase, runs, index)
    results["snapshots"] = snaps
    results["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    d = Path(settings.experiments_dir) / "studies" / spec.study_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"results_{phase}.json").write_text(json.dumps(clean_for_json(results), indent=1, default=str))
    return results


def summarise(
    spec: StudySpec, phase: str, runs: dict[tuple[str, str, str], ExperimentOutput], index: list[dict[str, Any]]
) -> dict[str, Any]:
    base_cfg = ExperimentConfig(name="pooled", country_iso3="XXX", commodity_codes=["x"], horizons=list(spec.horizons))
    groups: dict[tuple[str, str], list[str]] = {}
    for country, commodity, evidence in spec.cells(phase):
        groups.setdefault((country, evidence), []).append(commodity)
    pooled: list[dict[str, Any]] = []
    per_crop: list[dict[str, Any]] = []
    for (country, evidence), commodities in groups.items():

        def outs(variant: str, commodities: list[str] = commodities, country: str = country) -> list[ExperimentOutput]:
            return [runs[(country, k, variant)] for k in commodities if (country, k, variant) in runs]

        for h in spec.horizons:
            for variant in ("primary", "lag0", "lag2", "rawprecip"):
                if not outs(variant):
                    continue
                for a, b, label in CONTRASTS:
                    c = _slim(pooled_contrast(outs(variant), a, b, h, base_cfg, label))
                    if c:
                        pooled.append(
                            {"country": country, "evidence_class": evidence, "variant": variant, "contrast": label, **c}
                        )
            for variant in ("placebo_shift", "placebo_crop"):
                pairs = [
                    (runs[(country, k, "primary")], runs[(country, k, variant)])
                    for k in commodities
                    if (country, k, variant) in runs and (country, k, "primary") in runs
                ]
                if not pairs:
                    continue
                c = _slim(placebo_contrast([p[0] for p in pairs], [p[1] for p in pairs], h, base_cfg, variant))
                if c:
                    pooled.append(
                        {
                            "country": country,
                            "evidence_class": evidence,
                            "variant": variant,
                            "contrast": "P_vs_" + variant,
                            **c,
                        }
                    )
            for k in commodities:
                if (country, k, "primary") not in runs:
                    continue
                for a, b, label in CONTRASTS:
                    c = _slim(pooled_contrast([runs[(country, k, "primary")]], a, b, h, base_cfg, label))
                    if c:
                        per_crop.append(
                            {
                                "country": country,
                                "commodity_code": k,
                                "evidence_class": evidence,
                                "variant": "primary",
                                "contrast": label,
                                **c,
                            }
                        )
    # confirmatory family: primary variant, confirmatory countries, P vs A and P vs B, each horizon
    family = [
        r
        for r in pooled
        if r["evidence_class"] == "confirmatory"
        and r["variant"] == "primary"
        and r["contrast"] in CONFIRMATORY_CONTRASTS
    ]
    for r, p in zip(family, holm_adjust([r["p_b_better"] for r in family]), strict=True):
        r["p_holm"] = p
    decisions = [decide(r, pooled, spec.alpha) for r in family]
    return {
        "study_id": spec.study_id,
        "phase": phase,
        "spec": {
            "horizons": list(spec.horizons),
            "primary_lag": spec.primary_lag,
            "sensitivity_lags": list(spec.sensitivity_lags),
            "alpha": spec.alpha,
            "exploratory": {k: list(v) for k, v in spec.exploratory.items()},
            "confirmatory": {k: list(v) for k, v in spec.confirmatory.items()},
            "secondary": {k: list(v) for k, v in spec.secondary.items()},
            "placebo_shift_months": PLACEBO_SHIFT_MONTHS,
            "wrong_crop_map": WRONG_CROP,
        },
        "experiments": index,
        "pooled": pooled,
        "per_crop": per_crop,
        "confirmatory": {
            "n_tests": len(family),
            "method": "Holm step-down over the confirmatory family, one-sided HLN-corrected Diebold-Mariano",
            "decisions": decisions,
            "outcome": overall_outcome(decisions),
        },
    }


def decide(r: dict[str, Any], pooled: list[dict[str, Any]], alpha: float) -> dict[str, Any]:
    """Apply the protocol's decision rule to one confirmatory test."""
    placebo = next(
        (
            p
            for p in pooled
            if p["country"] == r["country"] and p["horizon"] == r["horizon"] and p["variant"] == "placebo_shift"
        ),
        None,
    )
    significant = r.get("p_holm") is not None and r["p_holm"] < alpha and (r["loss_ratio"] or 1) < 1
    stable = all(d is not None and d > 0 for d in r["subperiod_mean_diff"])
    beats_placebo = bool(placebo and placebo["p_b_better"] is not None and placebo["p_b_better"] < alpha)
    robust = not r.get("fragile")
    if significant and stable and beats_placebo and robust:
        outcome = "improvement_established"
    elif significant:
        outcome = "significant_but_unconfirmed"
    else:
        outcome = "no_established_improvement"
    return {
        "country": r["country"],
        "horizon": r["horizon"],
        "contrast": r["contrast"],
        "loss_ratio": r["loss_ratio"],
        "ci": [r["ci_low"], r["ci_high"]],
        "p_one_sided": r["p_b_better"],
        "p_holm": r.get("p_holm"),
        "holm_significant": significant,
        "stable_in_both_halves": stable,
        "beats_time_shift_placebo": beats_placebo,
        "not_fragile": robust,
        "outcome": outcome,
    }


def overall_outcome(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not decisions:
        return {"label": "not_run", "statement": "No confirmatory test was run."}
    n_ok = sum(d["outcome"] == "improvement_established" for d in decisions)
    n_sig = sum(d["holm_significant"] for d in decisions)
    below = sum((d["loss_ratio"] or 1) < 1 for d in decisions)
    if n_ok:
        label = "positive"
        text = (
            f"{n_ok} of {len(decisions)} confirmatory tests established an improvement from production-region "
            "weather that survived the Holm adjustment and every pre-specified check."
        )
    elif n_sig:
        label = "inconclusive"
        text = (
            f"{n_sig} of {len(decisions)} confirmatory tests were Holm-significant but failed a pre-specified "
            "stability, placebo or influence check; no improvement is established."
        )
    else:
        label = "no_established_improvement"
        text = (
            f"None of the {len(decisions)} confirmatory tests was significant after the Holm adjustment "
            f"({below} of {len(decisions)} point ratios were below 1). The study establishes no improvement from "
            "production-region weather. This is not evidence that weather has no effect: with roughly 65 "
            "monthly observations, improvements of a few percent in loss cannot be detected."
        )
    return {
        "label": label,
        "statement": text,
        "n_tests": len(decisions),
        "n_holm_significant": n_sig,
        "n_ratio_below_one": below,
    }
