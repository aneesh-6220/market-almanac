"""Experiment orchestration: selection -> features -> backtests -> inference -> conclusion.

The *primary*, pre-specified research comparisons are environment-enhanced (family B) versus
economic/price-only (family A) models of the same estimator class (ridge for log changes,
logistic for spikes) at each horizon. Everything else (trees, elastic net, families C/D,
alternative spike thresholds) is reported as sensitivity analysis and does not change the
headline verdict.
"""

from __future__ import annotations

import json
import platform
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from statsmodels.stats.diagnostic import acorr_ljungbox
from threadpoolctl import threadpool_limits

import shocktrace
from shocktrace.data.quality import EligibilityCriteria, assess_prices
from shocktrace.data.weather import PRECIP_QC_VERSION
from shocktrace.evaluation.backtest import (
    BacktestConfig,
    BacktestResult,
    InsufficientDataError,
    common_sample,
    run_backtest,
    sequential_interval_coverage,
)
from shocktrace.evaluation.inference import diebold_mariano, holm_adjust, moving_block_bootstrap_ratio
from shocktrace.evaluation.influence import influence_report
from shocktrace.evaluation.metrics import calibration_table, classification_metrics, regression_metrics
from shocktrace.experiments.config import ExperimentConfig
from shocktrace.features.builder import (
    AGRI_FEATURES,
    FEATURE_TRANSFORM_VERSION,
    MACRO_FEATURES,
    PRODUCTION_FEATURES,
    FeatureBuildResult,
    build_panel,
    timing_statement,
)
from shocktrace.features.production_weather import build_production_features
from shocktrace.features.weather import ClimatologyConfig, check_fixed_climatology
from shocktrace.forecasting.models import FittedModel, ModelSpec, default_specs

CAUSAL_DISCLAIMER = (
    "These are out-of-sample predictive comparisons. Improved prediction does not show that weather "
    "causes price changes; market-local weather is a geographic proxy, not crop-production exposure."
)

# Bumped whenever a change alters numerical results for an unchanged config (see docs/audits).
METHOD_REVISION = (
    "v1.0-2026-11: precipitation QC (precip-qc-1), price-release-lag scenarios, training targets must be "
    "published by the refit date, month-weighted bootstrap, Holm adjustment, influence diagnostics"
)
# Roles whose comparisons form the pre-specified family for the Holm adjustment.
PRIMARY_ROLES = ("primary", "primary_production", "production_vs_local")
PRODUCTION_PROXY_NOTE = (
    "Production-region weather weights NASA POWER cells by MapSPAM 2010 harvested area for the crop. It shows "
    "where the crop is grown nationally, not which farms supply a given market, and ignores imports and stocks."
)


def timing_disclosure(price_lag: int, weather_lag: int = 0) -> str:
    return "Timing classification: lag-assumption-based retrospective backtest. " + timing_statement(
        price_lag, weather_lag
    )


TIMING_DISCLOSURE = timing_disclosure(0)
VERDICTS = ("improved", "not_improved", "inconsistent", "insufficient_evidence")


@dataclass
class ExperimentOutput:
    experiment_id: str
    results: dict[str, Any]
    predictions: pd.DataFrame
    panel: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)


def _thr_tag(c: float) -> str:
    return f"t{round(c * 100)}"


def select_series(datasets: dict[str, pd.DataFrame], cfg: ExperimentConfig) -> tuple[list[str], list[dict[str, Any]]]:
    prices = datasets["prices"]
    sel = prices[(prices["country_iso3"] == cfg.country_iso3) & prices["commodity_code"].isin(cfg.commodity_codes)]
    if cfg.market_codes:
        sel = sel[sel["market_code"].isin(cfg.market_codes)]
    if cfg.price_types:
        sel = sel[sel["price_type"].isin(cfg.price_types)]
    if cfg.units:
        sel = sel[sel["unit"].isin(cfg.units)]
    quality, _ = assess_prices(sel, EligibilityCriteria(min_observations=cfg.min_series_observations))
    eligible = [q.series_id for q in quality if q.eligible]
    return eligible, [q.to_dict() for q in quality]


def _summarise_coefficients(coefs: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    rows = [c for c in coefs if c["model"] == model]
    if not rows:
        return []
    df = pd.DataFrame([c["coefficients"] for c in rows])
    out = []
    for f in df.columns:
        v = df[f].dropna()
        mean = float(v.mean())
        out.append(
            {
                "feature": f,
                "mean_std_coef": mean,
                "sd": float(v.std()) if len(v) > 1 else 0.0,
                "sign_stability": float(np.mean(np.sign(v) == np.sign(mean))) if mean != 0 else 0.0,
                "n_folds": len(v),
            }
        )
    return sorted(out, key=lambda r: -abs(r["mean_std_coef"]))


def _permutation(
    bt: BacktestResult, panel: pd.DataFrame, spec: ModelSpec, scoring: str, seed: int
) -> list[dict[str, Any]]:
    """Permutation importance of a model refit on the last fold's training window, scored on that
    fold's (out-of-sample) test rows."""
    cfg = bt.config
    if not bt.folds:
        return []
    last = bt.folds[-1]
    data = panel[panel[cfg.target].notna() & panel["log_price"].notna()].copy()
    data["target_period"] = data["origin"] + pd.DateOffset(months=cfg.h)
    c = pd.Timestamp(last["refit_date"])
    train = data[data["target_period"] + pd.DateOffset(months=cfg.price_release_lag) <= c]
    test = data[data["origin"] >= c]
    if len(test) < 20:
        return []
    m = FittedModel(spec, cfg.h, seed, cfg.price_release_lag).fit(train, cfg.target)
    if m.estimator is None:
        return []
    y = test[cfg.target].to_numpy(dtype=float)
    if spec.task == "classification" and len(np.unique(y)) < 2:
        return []
    r = permutation_importance(m.estimator, test[m.features], y, scoring=scoring, n_repeats=10, random_state=seed)
    out = [
        {"feature": f, "importance_mean": float(mu), "importance_sd": float(sd)}
        for f, mu, sd in zip(m.features, r.importances_mean, r.importances_std, strict=True)
    ]
    return sorted(out, key=lambda d: -d["importance_mean"])


def _compare(
    sample: pd.DataFrame,
    a: str,
    b: str,
    task: str,
    h: int,
    cfg: ExperimentConfig,
    role: str,
    row_meta: pd.DataFrame | None = None,
) -> dict[str, Any]:
    wide = sample.pivot_table(index=["series_id", "origin"], columns="model", values="pred", aggfunc="first")
    y = sample.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])["y"].reindex(wide.index)
    la = (wide[a] - y) ** 2
    lb = (wide[b] - y) ** 2
    dates = pd.Series(wide.index.get_level_values("origin"))
    dm = diebold_mariano(la.reset_index(drop=True), lb.reset_index(drop=True), dates, h, cfg.min_test_periods)
    la_r, lb_r = la.reset_index(drop=True), lb.reset_index(drop=True)
    boot = moving_block_bootstrap_ratio(la_r, lb_r, dates, h, cfg.bootstrap_reps, cfg.seed, weighting="months")
    boot_rows = moving_block_bootstrap_ratio(la_r, lb_r, dates, h, cfg.bootstrap_reps, cfg.seed, weighting="rows")
    infl_rows = pd.DataFrame(
        {
            "series_id": wide.index.get_level_values("series_id"),
            "origin": wide.index.get_level_values("origin"),
            "la": la.to_numpy(),
            "lb": lb.to_numpy(),
        }
    )
    if row_meta is not None:
        meta = row_meta.reindex(wide.index)
        infl_rows["location_id"] = meta["location_id"].to_numpy()
        infl_rows["qc_flag"] = meta["w_qc_flag"].to_numpy()
    influence = influence_report(infl_rows)
    pb = wide[b].to_numpy(dtype=float)
    yv = y.to_numpy(dtype=float)
    extremes = (
        {
            "max_abs_pred_a": float(np.max(np.abs(wide[a]))),
            "max_abs_pred_b": float(np.max(np.abs(pb))),
            "max_abs_actual": float(np.max(np.abs(yv))),
            "n_pred_b_beyond_actual_range": int(np.sum(np.abs(pb) > np.max(np.abs(yv)))),
        }
        if task == "regression"
        else None
    )
    # sub-period stability: sign of mean loss differential in each half of the test period
    ud = np.sort(dates.unique())
    halves: list[dict[str, Any]] = []
    if len(ud) >= 2:
        mid = ud[len(ud) // 2]
        for lo, hi, lab in ((ud[0], mid, "first_half"), (mid, ud[-1] + np.timedelta64(1, "D"), "second_half")):
            m = (dates >= lo) & (dates < hi)
            d = la.reset_index(drop=True)[m.values] - lb.reset_index(drop=True)[m.values]
            halves.append(
                {
                    "period": lab,
                    "start": str(pd.Timestamp(lo).date()),
                    "mean_diff": float(d.mean()) if len(d) else None,
                    "n": int(m.sum()),
                }
            )
    positives = int(y.sum()) if task == "classification" else None
    if dm.stat is None:
        verdict, reason = "insufficient_evidence", dm.note
    elif task == "classification" and positives is not None and positives < cfg.min_test_events:
        verdict, reason = "insufficient_evidence", f"only {positives} spike events in the test sample"
    else:
        alpha = cfg.significance_level
        better = dm.mean_diff > 0 and dm.p_value_b_better is not None and dm.p_value_b_better < alpha
        stable = all(hh["mean_diff"] is not None and hh["mean_diff"] > 0 for hh in halves)
        if better and stable:
            verdict, reason = (
                "improved",
                f"{b} has lower loss (one-sided HLN-DM p={dm.p_value_b_better:.3g}) in both halves",
            )
        elif better:
            verdict, reason = "inconsistent", "significant on the full sample but not in both sub-periods"
        elif dm.mean_diff < 0 and dm.p_value_two_sided is not None and dm.p_value_two_sided < alpha:
            verdict, reason = "not_improved", f"{b} is significantly worse (p={dm.p_value_two_sided:.3g})"
        else:
            verdict, reason = "not_improved", f"no significant difference (one-sided p={dm.p_value_b_better:.3g})"
    mae_a = float(np.mean(np.abs(wide[a] - y))) if task == "regression" else None
    mae_b = float(np.mean(np.abs(wide[b] - y))) if task == "regression" else None
    return {
        "role": role,
        "task": task,
        "horizon": h,
        "model_a": a,
        "model_b": b,
        "loss": "squared_error" if task == "regression" else "brier",
        "mean_loss_a": float(la.mean()),
        "mean_loss_b": float(lb.mean()),
        "relative_loss_b_vs_a": float(lb.mean() / la.mean()) if la.mean() > 0 else None,
        "mae_a": mae_a,
        "mae_b": mae_b,
        "n_rows": len(y),
        "positives": positives,
        "dm": dm.to_dict(),
        "bootstrap_loss_ratio": boot,
        "bootstrap_loss_ratio_row_weighted": boot_rows,
        "influence": influence,
        "prediction_extremes": extremes,
        "subperiods": halves,
        "verdict": verdict,
        "reason": reason,
    }


def _residual_diagnostics(sample: pd.DataFrame, model: str, h: int) -> dict[str, Any]:
    s = sample[sample["model"] == model]
    if s.empty:
        return {}
    r = (s["y"] - s["pred"]).groupby(s["origin"]).mean().sort_index()
    out: dict[str, Any] = {"mean": float(r.mean()), "sd": float(r.std()), "n_periods": len(r)}
    if len(r) > 24:
        acf = [float(r.autocorr(k)) for k in range(1, 13)]
        lb = acorr_ljungbox(r.to_numpy(), lags=[max(12, h)], return_df=True)
        out["acf"] = acf
        out["ljung_box_lag"] = int(max(12, h))
        out["ljung_box_p"] = float(lb["lb_pvalue"].iloc[0])
        out["note"] = (
            "Residual autocorrelation up to lag h-1 is expected for overlapping h-step forecasts." if h > 1 else ""
        )
    return out


def _task_block(
    bt: BacktestResult,
    panel: pd.DataFrame,
    specs: list[ModelSpec],
    task: str,
    h: int,
    cfg: ExperimentConfig,
    threshold: float | None,
    warnings: list[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    names = [s.name for s in specs]
    sample = common_sample(bt.predictions, names)
    meta_cols = ["series_id", "origin", "location_id", "w_qc_flag"]
    row_meta = (
        panel.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])[meta_cols[2:]]
        if all(c in panel.columns for c in meta_cols)
        else None
    )
    block: dict[str, Any] = {
        "task": task,
        "horizon": h,
        "target": bt.config.target,
        "threshold": threshold,
        "folds": bt.folds,
        "notes": bt.notes,
        "models": {},
        "comparisons": [],
    }
    if sample.empty:
        block["status"] = "insufficient_evidence"
        block["reason"] = "no test rows where every compared model produced a prediction"
        return block, sample
    block["test_period"] = [str(sample["origin"].min().date()), str(sample["origin"].max().date())]
    block["n_test_rows"] = int(sample.drop_duplicates(["series_id", "origin"]).shape[0])
    block["n_test_periods"] = int(sample["origin"].nunique())
    block["n_series"] = int(sample["series_id"].nunique())
    ref = "naive" if task == "regression" else "climatology"
    r_ref = sample[sample["model"] == ref]
    if task == "regression":
        e = r_ref["pred"] - r_ref["y"]
        ref_mae, ref_rmse = float(np.mean(np.abs(e))), float(np.sqrt(np.mean(e**2)))
    else:
        ref_brier = float(np.mean((r_ref["pred"] - r_ref["y"]) ** 2))
    for s in specs:
        r = sample[sample["model"] == s.name]
        y, p = r["y"].to_numpy(dtype=float), r["pred"].to_numpy(dtype=float)
        if task == "regression":
            met = regression_metrics(y, p, ref_mae, ref_rmse, is_naive=s.name == "naive")
            met["interval_coverage"] = sequential_interval_coverage(
                r, h, price_release_lag=cfg.price_release_lag_months
            )
        else:
            met = classification_metrics(
                y, p, r["decision_threshold"].to_numpy(dtype=float), ref_brier, cfg.min_test_events
            )
            met["calibration"] = calibration_table(y, p)
        # breakdowns
        by_series = r.assign(ae=np.abs(r["pred"] - r["y"]), se=(r["pred"] - r["y"]) ** 2).groupby("series_id")
        met["by_series"] = {
            sid: {
                "n": len(g),
                "mae" if task == "regression" else "brier": float(
                    g["ae"].mean() if task == "regression" else g["se"].mean()
                ),
            }
            for sid, g in by_series
        }
        by_year = r.assign(
            ae=np.abs(r["pred"] - r["y"]), se=(r["pred"] - r["y"]) ** 2, year=pd.to_datetime(r["origin"]).dt.year
        ).groupby("year")
        met["by_year"] = {
            int(yr): {
                "n": len(g),
                "mae" if task == "regression" else "brier": float(
                    g["ae"].mean() if task == "regression" else g["se"].mean()
                ),
            }
            for yr, g in by_year
        }
        met["spec"] = {"kind": s.kind, "family": s.family, "estimator": s.estimator, "description": s.description}
        if s.kind == "linear":
            met["coefficients"] = _summarise_coefficients(bt.coefficients, s.name)
            met["selected_params"] = [c["params"] for c in bt.coefficients if c["model"] == s.name]
        block["models"][s.name] = met
    # comparisons
    fams = sorted({s.family for s in specs if s.family})
    est = "ridge" if task == "regression" else "logit"
    if "A" in fams and "B" in fams:
        block["comparisons"].append(_compare(sample, f"{est}_A", f"{est}_B", task, h, cfg, "primary", row_meta))
    if "A" in fams and "P" in fams:
        block["comparisons"].append(
            _compare(sample, f"{est}_A", f"{est}_P", task, h, cfg, "primary_production", row_meta)
        )
    if "B" in fams and "P" in fams:
        block["comparisons"].append(
            _compare(sample, f"{est}_B", f"{est}_P", task, h, cfg, "production_vs_local", row_meta)
        )
    for x, y_ in (("B", "C"), ("C", "D")):
        if x in fams and y_ in fams:
            block["comparisons"].append(_compare(sample, f"{est}_{x}", f"{est}_{y_}", task, h, cfg, "secondary"))
    tree = "gbr" if task == "regression" else "gbc"
    if f"{tree}_A" in names and f"{tree}_B" in names:
        block["comparisons"].append(_compare(sample, f"{tree}_A", f"{tree}_B", task, h, cfg, "specification"))
    if task == "regression" and "enet_A" in names and "enet_B" in names:
        block["comparisons"].append(_compare(sample, "enet_A", "enet_B", task, h, cfg, "specification"))
    for m in (f"{est}_A", f"{est}_B", f"{est}_P"):
        if m in names:
            block["comparisons"].append(_compare(sample, ref, m, task, h, cfg, "vs_baseline"))
    if task == "regression":
        block["residual_diagnostics"] = {
            m: _residual_diagnostics(sample, m, h) for m in ("ridge_A", "ridge_B", "ridge_P") if m in names
        }
        scoring = "neg_mean_absolute_error"
    else:
        scoring = "neg_brier_score"
    block["permutation_importance"] = {}
    for s in specs:
        if s.name in (f"{est}_B", f"{tree}_B"):
            try:
                block["permutation_importance"][s.name] = _permutation(bt, panel, s, scoring, cfg.seed)
            except ValueError as exc:
                warnings.append(f"permutation importance for {s.name} failed: {exc}")
    block["status"] = "ok"
    return block, sample


def overall_conclusion(
    comparisons: list[dict[str, Any]], role: str = "primary", subject: str = "Environmental features"
) -> dict[str, Any]:
    prim = [c for c in comparisons if c["role"] == role]
    suff = [c for c in prim if c["verdict"] != "insufficient_evidence"]
    if not suff:
        verdict = "insufficient_evidence"
    elif all(c["verdict"] == "improved" for c in suff):
        verdict = "improved"
    elif not any(c["verdict"] in ("improved", "inconsistent") for c in suff):
        verdict = "not_improved"
    else:
        verdict = "inconsistent"
    statements = {
        "improved": (f"{subject} improved out-of-sample prediction in every pre-specified primary comparison."),
        "not_improved": (
            f"{subject} did not materially improve out-of-sample prediction in the pre-specified primary comparisons."
        ),
        "inconsistent": (
            f"Evidence is mixed: {subject.lower()} improved prediction in some primary comparisons "
            "or sub-periods but not others."
        ),
        "insufficient_evidence": "The available data cannot support a reliable comparison; no conclusion is drawn.",
    }
    return {
        "verdict": verdict,
        "statement": statements[verdict],
        "primary_comparisons": [
            {
                **{
                    k: c[k]
                    for k in ("task", "horizon", "model_a", "model_b", "verdict", "reason", "relative_loss_b_vs_a")
                },
                "fragile": bool((c.get("influence") or {}).get("fragile", False)),
            }
            for c in prim
        ],
        "n_fragile": sum(bool((c.get("influence") or {}).get("fragile", False)) for c in prim),
        "n_primary": len(prim),
        "n_sufficient": len(suff),
        "decision_rule": (
            "A primary comparison counts as 'improved' when the environment-enhanced model's mean loss is lower, "
            "the one-sided HLN-corrected Diebold-Mariano test (HAC, origin-month aggregated) rejects equal "
            "accuracy at the configured significance level, and the loss differential favours the enhanced "
            "model in both halves of the test period."
        ),
        "causal_disclaimer": CAUSAL_DISCLAIMER,
    }


def qualify_forecast(block: dict[str, Any] | None, model: str, cfg: ExperimentConfig) -> tuple[str, str]:
    """Validation status for forward forecasts. 'validated_*' requires an actual evaluation."""
    if not block or block.get("status") != "ok" or model not in block.get("models", {}):
        return "not_evaluated", "no out-of-sample evaluation exists for this model and horizon"
    n_periods = block.get("n_test_periods", 0)
    if n_periods < cfg.min_test_periods:
        return "insufficient_validation", f"only {n_periods} test periods"
    vs = next((c for c in block["comparisons"] if c["role"] == "vs_baseline" and c["model_b"] == model), None)
    if vs is None or vs["dm"]["stat"] is None:
        return "insufficient_validation", "no baseline comparison available"
    if vs["verdict"] == "insufficient_evidence":
        return "insufficient_validation", vs["reason"]
    if vs["mean_loss_b"] < vs["mean_loss_a"] and (vs["dm"]["p_value_b_better"] or 1) < 0.10:
        return (
            "validated_outperforms_baseline",
            f"beats {vs['model_a']} out of sample (p={vs['dm']['p_value_b_better']:.3g})",
        )
    return "validated_no_better_than_baseline", f"does not significantly beat {vs['model_a']} out of sample"


def _forward_forecasts(
    fb: FeatureBuildResult,
    reg: dict[int, tuple[BacktestResult, dict[str, Any], pd.DataFrame]],
    clf: dict[int, tuple[BacktestResult, dict[str, Any], pd.DataFrame]],
    cfg: ExperimentConfig,
    experiment_id: str,
) -> list[dict[str, Any]]:
    panel = fb.panel
    out: list[dict[str, Any]] = []
    last_month = panel.loc[panel["log_price"].notna(), "origin"].max()
    meta = fb.series_meta.set_index("series_id")
    lag = cfg.price_release_lag_months
    for sid, g in panel[panel["log_price"].notna()].groupby("series_id"):
        row = g.sort_values("origin").iloc[[-1]]
        origin = row["origin"].iloc[0]
        ref_period = pd.Timestamp(row["price_ref_period"].iloc[0])
        stale = origin < last_month - pd.DateOffset(months=2)
        m = meta.loc[sid]
        for h in cfg.horizons:
            for task, store, model in (
                ("regression", reg, cfg.primary_regression_model),
                ("classification", clf, cfg.primary_classification_model),
            ):
                base = {
                    "experiment_id": experiment_id,
                    "series_id": sid,
                    "task": task,
                    "horizon": h,
                    "model": model,
                    "origin_period": origin.date().isoformat(),
                    "target_period": (origin + pd.DateOffset(months=h)).date().isoformat(),
                    "information_cutoff": origin.date().isoformat(),
                    "last_price_period": ref_period.date().isoformat(),
                    "price_release_lag_months": lag,
                    "market_name": str(m["market_name"]),
                    "commodity_name": str(m["commodity_name"]),
                    "unit": str(m["unit"]),
                    "currency": str(m["currency"]),
                    "last_price": float(row["price"].iloc[0]),
                    "threshold": cfg.spike_threshold if task == "classification" else None,
                }
                entry = store.get(h)
                block = entry[1] if entry else None
                vstatus, vreason = qualify_forecast(block, model, cfg)
                if stale:
                    out.append(
                        {
                            **base,
                            "status": "withheld",
                            "validation_status": vstatus,
                            "reason": f"series last observed {ref_period:%Y-%m}; "
                            "more than 2 months before the latest data",
                        }
                    )
                    continue
                if vstatus in ("not_evaluated", "insufficient_validation") or entry is None:
                    out.append({**base, "status": "withheld", "validation_status": vstatus, "reason": vreason})
                    continue
                bt, _, sample = entry
                fm = bt.final_models.get(model)
                if fm is None:
                    out.append(
                        {**base, "status": "withheld", "validation_status": vstatus, "reason": "model not fitted"}
                    )
                    continue
                pred = float(fm.predict(row)[0])
                rec = {**base, "status": "issued", "validation_status": vstatus, "reason": vreason}
                if task == "regression":
                    s = sample[sample["model"] == model]
                    resid = (s["y"] - s["pred"]).to_numpy()
                    q = np.quantile(resid, [0.025, 0.1, 0.9, 0.975])
                    p0 = rec["last_price"]
                    rec.update(
                        {
                            "point_log_change": pred,
                            "point_price": p0 * float(np.exp(pred)),
                            "lower80": p0 * float(np.exp(pred + q[1])),
                            "upper80": p0 * float(np.exp(pred + q[2])),
                            "lower95": p0 * float(np.exp(pred + q[0])),
                            "upper95": p0 * float(np.exp(pred + q[3])),
                            "interval_method": "empirical quantiles of out-of-sample backtest residuals",
                        }
                    )
                else:
                    rec.update({"probability": pred, "decision_threshold": fm.decision_threshold})
                out.append(rec)
    return out


def run_experiment(
    datasets: dict[str, pd.DataFrame],
    cfg: ExperimentConfig,
    *,
    mode: str,
    snapshots: dict[str, dict[str, Any]] | None = None,
    synthetic: bool = False,
    experiment_id: str | None = None,
) -> ExperimentOutput:
    # Small panels: BLAS/OpenMP thread pools cost more than they save; keep training bounded.
    with threadpool_limits(limits=1):
        return _run_experiment(
            datasets, cfg, mode=mode, snapshots=snapshots, synthetic=synthetic, experiment_id=experiment_id
        )


def _run_experiment(
    datasets: dict[str, pd.DataFrame],
    cfg: ExperimentConfig,
    *,
    mode: str,
    snapshots: dict[str, dict[str, Any]] | None,
    synthetic: bool,
    experiment_id: str | None,
) -> ExperimentOutput:
    experiment_id = experiment_id or f"exp_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"
    warnings: list[str] = []
    created = datetime.now(UTC).isoformat()
    results: dict[str, Any] = {
        "experiment_id": experiment_id,
        "name": cfg.name,
        "mode": mode,
        "synthetic": synthetic,
        "created_at": created,
        "config": cfg.model_dump(),
        "config_hash": cfg.config_hash(),
        "tasks": [],
        "sensitivity": [],
        "forecasts": [],
        "warnings": warnings,
    }
    results["manifest"] = {
        "software_version": shocktrace.__version__,
        "method_revision": METHOD_REVISION,
        "feature_transform_version": FEATURE_TRANSFORM_VERSION,
        "precip_qc_version": PRECIP_QC_VERSION,
        "evidence_class": cfg.evidence_class,
        "study": cfg.study,
        "timing": {
            "price_release_lag_months": cfg.price_release_lag_months,
            "weather_release_lag_months": cfg.weather_release_lag_months,
            "statement": timing_statement(cfg.price_release_lag_months, cfg.weather_release_lag_months),
            "verified_point_in_time": False,
        },
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": __import__("sklearn").__version__,
        "statsmodels": __import__("statsmodels").__version__,
        "random_seed": cfg.seed,
        "snapshots": snapshots or {},
        "synthetic": synthetic,
        "retrospective_note": (
            "Retrospective pseudo-out-of-sample experiment on the current data vintage. Publication dates are "
            "unknown for most inputs, so conservative release lags are applied; this is not a true real-time "
            "(point-in-time vintage) backtest and makes no claim of historical investability."
        ),
    }
    eligible, quality = select_series(datasets, cfg)
    results["series_quality"] = quality
    results["eligible_series"] = eligible
    if not eligible:
        results["conclusion"] = overall_conclusion([])
        results["conclusion"]["statement"] = "No eligible price series matched the selection; no conclusion is drawn."
        results["status"] = "insufficient_evidence"
        return ExperimentOutput(experiment_id, results, pd.DataFrame(), None, warnings)

    clim = ClimatologyConfig(
        cfg.climatology_mode,
        cfg.climatology_fixed_start_year,
        cfg.climatology_fixed_end_year,
        cfg.climatology_min_years,
    )
    prod = datasets.get("production_features")
    if "P" in cfg.families:
        if prod is None:
            px = datasets["prices"]
            names = (
                px[px["series_id"].isin(eligible)]
                .drop_duplicates("commodity_code")
                .set_index("commodity_code")["commodity_name"]
                .to_dict()
            )
            prod, prod_meta = build_production_features(
                datasets.get("weather_monthly", pd.DataFrame()),
                cfg.country_iso3,
                {str(k): str(v) for k, v in names.items()},
                clim,
                weather_release_lag=cfg.weather_release_lag_months,
                use_precip_qc=cfg.use_precip_qc,
            )
            results["production_region"] = prod_meta
        else:
            results["production_region"] = {"status": "features supplied by the caller (falsification variant)"}
    fb = build_panel(
        datasets,
        eligible,
        tuple(cfg.horizons),
        tuple(cfg.sensitivity_thresholds),
        clim,
        price_release_lag=cfg.price_release_lag_months,
        weather_release_lag=cfg.weather_release_lag_months,
        production_features=prod,
        use_precip_qc=cfg.use_precip_qc,
    )
    warnings.extend(fb.warnings)
    results["feature_availability"] = fb.availability
    panel = fb.panel
    first_origin = panel.loc[panel["log_price"].notna(), "origin"].min()
    check_fixed_climatology(clim, first_origin + pd.DateOffset(months=cfg.min_train_months))
    results["data"] = {
        "n_series": len(eligible),
        "panel_rows": len(panel),
        "first_origin": str(first_origin.date()),
        "last_origin": str(panel.loc[panel["log_price"].notna(), "origin"].max().date()),
        "series": [
            {k: (v if not isinstance(v, float) or np.isfinite(v) else None) for k, v in r.items()}
            for r in fb.series_meta[
                [
                    "series_id",
                    "market_name",
                    "market_code",
                    "commodity_name",
                    "commodity_code",
                    "unit",
                    "price_type",
                    "currency",
                    "lat",
                    "lon",
                ]
            ].to_dict("records")
        ],
    }
    families = list(cfg.families)
    for fam, cols in (("C", MACRO_FEATURES), ("D", AGRI_FEATURES), ("P", PRODUCTION_FEATURES)):
        if fam in families and panel[list(cols)].isna().all().all():
            families = [f for f in families if f != fam and not (fam == "C" and f == "D")]
            warnings.append(f"feature family {fam} skipped: none of its features are available for the selected series")
    results["families_used"] = families
    specs = default_specs(tuple(families), cfg.include_trees)
    reg_specs = [s for s in specs if s.task == "regression"]
    clf_specs = [s for s in specs if s.task == "classification"]
    all_preds = []
    reg_store: dict[int, tuple[BacktestResult, dict[str, Any], pd.DataFrame]] = {}
    clf_store: dict[int, tuple[BacktestResult, dict[str, Any], pd.DataFrame]] = {}
    for h in cfg.horizons:
        for task, task_specs, target, thr in (
            ("regression", reg_specs, f"y_dlog_h{h}", None),
            ("classification", clf_specs, f"y_spike_h{h}_{_thr_tag(cfg.spike_threshold)}", cfg.spike_threshold),
        ):
            bcfg = BacktestConfig(
                h=h,
                target=target,
                task=task,
                min_train_months=cfg.min_train_months,
                refit_every=cfg.refit_every,
                seed=cfg.seed,
                price_release_lag=cfg.price_release_lag_months,
            )
            try:
                bt = run_backtest(panel, task_specs, bcfg)
            except InsufficientDataError as exc:
                results["tasks"].append(
                    {
                        "task": task,
                        "horizon": h,
                        "target": target,
                        "threshold": thr,
                        "status": "insufficient_evidence",
                        "reason": str(exc),
                        "comparisons": [],
                    }
                )
                continue
            block, sample = _task_block(bt, panel, task_specs, task, h, cfg, thr, warnings)
            results["tasks"].append(block)
            (reg_store if task == "regression" else clf_store)[h] = (bt, block, sample)
            all_preds.append(bt.predictions.assign(task=task, horizon=h, threshold=thr))
    # threshold sensitivity (classification, A vs B only)
    sens_specs = [s for s in clf_specs if s.name in ("climatology", "logit_A", "logit_B")]
    for h in cfg.horizons:
        for c in cfg.sensitivity_thresholds:
            target = f"y_spike_h{h}_{_thr_tag(c)}"
            try:
                bt = run_backtest(
                    panel,
                    sens_specs,
                    BacktestConfig(
                        h,
                        target,
                        "classification",
                        cfg.min_train_months,
                        cfg.refit_every,
                        seed=cfg.seed,
                        price_release_lag=cfg.price_release_lag_months,
                    ),
                )
            except InsufficientDataError as exc:
                results["sensitivity"].append(
                    {"horizon": h, "threshold": c, "status": "insufficient_evidence", "reason": str(exc)}
                )
                continue
            sample = common_sample(bt.predictions, [s.name for s in sens_specs])
            if sample.empty or "logit_B" not in set(sample["model"]):
                results["sensitivity"].append({"horizon": h, "threshold": c, "status": "insufficient_evidence"})
                continue
            comp = _compare(sample, "logit_A", "logit_B", "classification", h, cfg, "sensitivity")
            results["sensitivity"].append(
                {
                    "horizon": h,
                    "threshold": c,
                    "status": "ok",
                    "event_rate": float(sample.drop_duplicates(["series_id", "origin"])["y"].mean()),
                    **{
                        k: comp[k]
                        for k in (
                            "positives",
                            "mean_loss_a",
                            "mean_loss_b",
                            "relative_loss_b_vs_a",
                            "verdict",
                            "reason",
                        )
                    },
                    "dm_p_b_better": comp["dm"]["p_value_b_better"],
                }
            )
    comparisons = [c for t in results["tasks"] for c in t.get("comparisons", [])]
    family = [c for c in comparisons if c["role"] in PRIMARY_ROLES]
    adjusted = holm_adjust([c["dm"]["p_value_b_better"] for c in family])
    for c, p_adj in zip(family, adjusted, strict=True):
        c["dm"]["p_value_b_better_holm"] = p_adj
    results["multiplicity"] = {
        "method": "Holm step-down",
        "family": "all pre-specified comparisons in this experiment (roles: " + ", ".join(PRIMARY_ROLES) + ")",
        "n_tests": sum(p is not None for p in adjusted),
        "min_adjusted_p": min((p for p in adjusted if p is not None), default=None),
        "note": "Verdicts use unadjusted one-sided p-values; a result is only called confirmed if it also "
        "survives the Holm adjustment across the experiment's pre-specified family.",
    }
    results["conclusion"] = overall_conclusion(comparisons)
    if "P" in families:
        results["production_conclusion"] = overall_conclusion(
            comparisons, "primary_production", "Production-region crop-season weather features"
        )
        results["production_vs_local_conclusion"] = overall_conclusion(
            comparisons, "production_vs_local", "Production-region features (relative to market-local weather)"
        )
    results["evidence_class"] = cfg.evidence_class
    results["forecasts"] = _forward_forecasts(fb, reg_store, clf_store, cfg, experiment_id)
    results["status"] = "completed"
    results["limitations"] = [
        CAUSAL_DISCLAIMER,
        "Market-local weather is measured at the market's POWER grid cell (~50 km), "
        "not where the commodity was produced.",
        results["manifest"]["retrospective_note"],
        timing_disclosure(cfg.price_release_lag_months, cfg.weather_release_lag_months),
        "Pooled models assume comparable dynamics across the selected series.",
    ]
    if "P" in families:
        results["limitations"].append(PRODUCTION_PROXY_NOTE)
    if cfg.evidence_class == "exploratory":
        results["limitations"].append(
            "Exploratory evidence: this evaluation period was examined while the method was being developed, "
            "so its results cannot confirm a hypothesis."
        )
    if synthetic:
        results["limitations"].insert(
            0, "SYNTHETIC DEMO DATA: results describe the demo data-generating process, not any real market."
        )
    preds = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    return ExperimentOutput(experiment_id, results, preds, panel, warnings)


def _json_default(o: Any) -> Any:
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def clean_for_json(obj: Any) -> Any:
    """Recursively replace NaN/inf with None so output is strict JSON."""
    if isinstance(obj, dict):
        return {str(k): clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_for_json(v) for v in obj]
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    if isinstance(obj, (np.floating, np.integer, pd.Timestamp, np.ndarray, datetime, Path)):
        return clean_for_json(_json_default(obj))
    return obj


def save_experiment(out: ExperimentOutput, root: Path) -> Path:
    d = root / out.experiment_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps(clean_for_json(out.results), indent=1, default=_json_default))
    (d / "config.json").write_text(json.dumps(out.results["config"], indent=1))
    manifest = {
        **out.results["manifest"],
        "experiment_id": out.experiment_id,
        "config": out.results["config"],
        "config_hash": out.results["config_hash"],
        "eligible_series": out.results.get("eligible_series"),
        "conclusion": out.results.get("conclusion", {}).get("verdict"),
        "warnings": out.results.get("warnings"),
        "limitations": out.results.get("limitations"),
    }
    (d / "manifest.json").write_text(json.dumps(clean_for_json(manifest), indent=1, default=_json_default))
    if not out.predictions.empty:
        out.predictions.to_parquet(d / "predictions.parquet", index=False)
    if out.panel is not None:
        out.panel.to_parquet(d / "features.parquet", index=False)
    return d
