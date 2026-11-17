"""Expanding-window, rolling-origin backtesting.

For horizon h and refit date c (a month):

* training rows: origins s with s + h + L <= c, where L is the assumed price release lag. The
  target price P_{s+h} must be *realised and published* by c; "s < c" alone would leak
  overlapping targets for h > 1, and "s + h <= c" alone would train on prices that the lag
  assumption says were not yet available;
* test rows:     origins t with c <= t < c + refit_every.

There is no shuffling; preprocessing and hyper-parameter selection happen inside each fit on
training rows only. Each prediction records its information cutoff (= origin) and the last
training origin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from shocktrace.forecasting.models import FittedModel, ModelSpec


class InsufficientDataError(ValueError):
    """The evidence base cannot support a backtest; ShockTrace refuses rather than guesses."""


@dataclass
class BacktestConfig:
    h: int
    target: str
    task: str
    min_train_months: int = 48
    refit_every: int = 12
    min_train_rows: int = 60
    seed: int = 42
    price_release_lag: int = 0  # months after month m before P_m is assumed published


@dataclass
class BacktestResult:
    config: BacktestConfig
    predictions: pd.DataFrame
    folds: list[dict[str, Any]]
    coefficients: list[dict[str, Any]] = field(default_factory=list)
    final_models: dict[str, FittedModel] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def refit_schedule(origins: pd.Series, cfg: BacktestConfig) -> list[pd.Timestamp]:
    o = pd.to_datetime(pd.Series(origins.unique())).sort_values()
    if o.empty:
        return []
    first = o.iloc[0] + pd.DateOffset(months=cfg.min_train_months)
    last = o.iloc[-1]
    if first > last:
        return []
    return list(pd.date_range(first, last, freq=f"{cfg.refit_every}MS"))


def run_backtest(panel: pd.DataFrame, specs: list[ModelSpec], cfg: BacktestConfig) -> BacktestResult:
    if cfg.target not in panel:
        raise KeyError(cfg.target)
    data = panel[panel[cfg.target].notna() & panel["log_price"].notna()].copy()
    data["target_period"] = data["origin"] + pd.DateOffset(months=cfg.h)
    lag = pd.DateOffset(months=cfg.price_release_lag)
    schedule = refit_schedule(data["origin"], cfg)
    if not schedule:
        raise InsufficientDataError(
            f"history shorter than the minimum training window ({cfg.min_train_months} months) plus one test origin"
        )
    preds, folds, coefs, notes = [], [], [], []
    for k, c in enumerate(schedule):
        c_next = schedule[k + 1] if k + 1 < len(schedule) else data["origin"].max() + pd.DateOffset(months=1)
        train = data[data["target_period"] + lag <= c]
        test = data[(data["origin"] >= c) & (data["origin"] < c_next)]
        if test.empty:
            continue
        if len(train) < cfg.min_train_rows:
            notes.append(f"fold {c:%Y-%m}: skipped, {len(train)} training rows < {cfg.min_train_rows}")
            continue
        assert (train["target_period"] + lag).max() <= c, "leakage guard: training target not published by cutoff"
        assert test["origin"].min() >= c
        folds.append(
            {
                "fold": k,
                "refit_date": c.date().isoformat(),
                "train_rows": len(train),
                "train_first_origin": train["origin"].min().date().isoformat(),
                "train_last_origin": train["origin"].max().date().isoformat(),
                "test_rows": len(test),
                "test_first_origin": test["origin"].min().date().isoformat(),
                "test_last_origin": test["origin"].max().date().isoformat(),
            }
        )
        for spec in specs:
            m = FittedModel(spec, cfg.h, cfg.seed, cfg.price_release_lag).fit(train, cfg.target)
            p = m.predict(test)
            preds.append(
                pd.DataFrame(
                    {
                        "series_id": test["series_id"].to_numpy(),
                        "origin": test["origin"].to_numpy(),
                        "target_period": test["target_period"].to_numpy(),
                        "y": test[cfg.target].to_numpy(dtype=float),
                        "pred": p,
                        "model": spec.name,
                        "fold": k,
                        "refit_date": c,
                        "train_last_origin": train["origin"].max(),
                        "n_train": len(train),
                        "decision_threshold": m.decision_threshold,
                    }
                )
            )
            cf = m.coefficients()
            if cf is not None:
                coefs.append(
                    {
                        "model": spec.name,
                        "fold": k,
                        "refit_date": c.date().isoformat(),
                        "params": m.params,
                        "coefficients": cf,
                        "dropped": m.dropped_features,
                    }
                )
    if not preds:
        raise InsufficientDataError("no fold had enough training data")
    pred_df = pd.concat(preds, ignore_index=True)
    # final models on all realised data (used for forward forecasts and interpretation)
    final: dict[str, FittedModel] = {}
    for spec in specs:
        final[spec.name] = FittedModel(spec, cfg.h, cfg.seed, cfg.price_release_lag).fit(data, cfg.target)
    return BacktestResult(cfg, pred_df, folds, coefs, final, notes)


def common_sample(preds: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Rows (series, origin) for which every listed model produced a finite prediction."""
    sub = preds[preds["model"].isin(models)]
    wide = sub.pivot_table(index=["series_id", "origin"], columns="model", values="pred", aggfunc="first")
    if sub.empty or any(m not in wide.columns for m in models):
        return sub.iloc[0:0].reset_index(drop=True)  # a model never predicted: no common sample
    ok = wide[models].notna().all(axis=1) & np.isfinite(wide[models]).all(axis=1)
    keys = wide.index[ok]
    return sub.set_index(["series_id", "origin"]).loc[lambda d: d.index.isin(keys)].reset_index()


def sequential_interval_coverage(
    preds: pd.DataFrame,
    h: int,
    levels: tuple[float, ...] = (0.8, 0.95),
    min_resid: int = 30,
    price_release_lag: int = 0,
) -> dict[str, Any]:
    """Empirical coverage of residual-quantile intervals built only from earlier realised errors.

    For each prediction at origin t, the interval uses residuals of predictions whose targets
    were realised and published by t (origin_j + h + L <= t). This mimics what a forecaster
    could have known.
    """
    p = preds.sort_values("origin").reset_index(drop=True)
    resid = (p["y"] - p["pred"]).to_numpy()
    realised = (p["origin"] + pd.DateOffset(months=h + price_release_lag)).to_numpy()
    origins = p["origin"].to_numpy()
    hits: dict[float, list[bool]] = {lv: [] for lv in levels}
    for i in range(len(p)):
        prior = resid[realised <= origins[i]]
        if len(prior) < min_resid:
            continue
        for lv in levels:
            lo, hi = np.quantile(prior, [(1 - lv) / 2, 1 - (1 - lv) / 2])
            hits[lv].append(lo <= resid[i] <= hi)
    return {
        f"{int(lv * 100)}": {"nominal": lv, "empirical": float(np.mean(v)) if v else None, "n": len(v)}
        for lv, v in hits.items()
    }
