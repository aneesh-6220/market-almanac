"""Forecasting models: transparent baselines first, then a restrained set of estimators.

All learned preprocessing (median imputation, standardisation) lives *inside* an sklearn
Pipeline that is fit on training rows only. Hyper-parameters are chosen by an inner,
chronologically ordered validation split inside the training window (with a purge gap so
inner-training targets are realised before the validation origins).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from shocktrace.features.builder import family_features

INNER_VALIDATION_MONTHS = 24
MAX_MISSING_SHARE = 0.5


@dataclass
class ModelSpec:
    name: str
    task: str  # regression | classification
    kind: str  # baseline | linear | tree
    family: str | None  # A|B|C|D for learned models
    estimator: str  # naive | seasonal_naive | climatology | ridge | enet | logit | gbr | gbc
    description: str
    grid: list[dict[str, Any]] = field(default_factory=list)


def default_specs(families: tuple[str, ...], include_trees: bool = True) -> list[ModelSpec]:
    specs = [
        ModelSpec(
            "naive",
            "regression",
            "baseline",
            None,
            "naive",
            "Last observation (random walk in logs): predicted change = 0",
        ),
        ModelSpec(
            "seasonal_naive",
            "regression",
            "baseline",
            None,
            "seasonal_naive",
            "Same-horizon log change observed one year earlier",
        ),
        ModelSpec(
            "climatology",
            "classification",
            "baseline",
            None,
            "climatology",
            "Training-window spike frequency (unconditional base rate)",
        ),
    ]
    alphas = [{"alpha": a} for a in (0.1, 1.0, 10.0, 100.0, 1000.0)]
    cs = [{"C": c} for c in (0.01, 0.1, 1.0, 10.0)]
    for fam in families:
        specs.append(
            ModelSpec(
                f"ridge_{fam}", "regression", "linear", fam, "ridge", f"Ridge regression, feature family {fam}", alphas
            )
        )
        specs.append(
            ModelSpec(
                f"logit_{fam}",
                "classification",
                "linear",
                fam,
                "logit",
                f"L2 logistic regression, feature family {fam}",
                cs,
            )
        )
    if "B" in families and "A" in families:
        specs.append(
            ModelSpec(
                "enet_A",
                "regression",
                "linear",
                "A",
                "enet",
                "Elastic net, family A",
                [{"alpha": a, "l1_ratio": 0.5} for a in (0.0005, 0.005, 0.05)],
            )
        )
        specs.append(
            ModelSpec(
                "enet_B",
                "regression",
                "linear",
                "B",
                "enet",
                "Elastic net, family B",
                [{"alpha": a, "l1_ratio": 0.5} for a in (0.0005, 0.005, 0.05)],
            )
        )
        if include_trees:
            tg = [{"max_depth": d, "learning_rate": 0.05, "max_iter": 150} for d in (2, 3)]
            specs.append(ModelSpec("gbr_A", "regression", "tree", "A", "gbr", "Gradient boosting, family A", tg))
            specs.append(ModelSpec("gbr_B", "regression", "tree", "B", "gbr", "Gradient boosting, family B", tg))
            specs.append(
                ModelSpec("gbc_A", "classification", "tree", "A", "gbc", "Gradient boosting clf., family A", tg)
            )
            specs.append(
                ModelSpec("gbc_B", "classification", "tree", "B", "gbc", "Gradient boosting clf., family B", tg)
            )
    return specs


def _make_estimator(spec: ModelSpec, params: dict[str, Any], seed: int) -> BaseEstimator:
    if spec.estimator == "ridge":
        return Pipeline(
            [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", Ridge(**params))]
        )
    if spec.estimator == "enet":
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("model", ElasticNet(max_iter=5000, random_state=seed, **params)),
            ]
        )
    if spec.estimator == "logit":
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=2000, **params)),
            ]
        )
    if spec.estimator == "gbr":
        return HistGradientBoostingRegressor(random_state=seed, l2_regularization=1.0, min_samples_leaf=20, **params)
    if spec.estimator == "gbc":
        return HistGradientBoostingClassifier(random_state=seed, l2_regularization=1.0, min_samples_leaf=20, **params)
    raise ValueError(spec.estimator)


def _loss(task: str) -> Callable[[np.ndarray, np.ndarray], float]:
    if task == "regression":
        return lambda y, p: float(np.mean((y - p) ** 2))
    return lambda y, p: float(np.mean((y - p) ** 2))  # Brier score for probabilities


def _predict(est: BaseEstimator, task: str, X: pd.DataFrame) -> np.ndarray:
    if task == "classification":
        return est.predict_proba(X)[:, 1]  # type: ignore[attr-defined]
    return est.predict(X)  # type: ignore[attr-defined]


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """Decision threshold maximising F1 on (training-window) validation predictions."""
    if len(y) == 0 or y.sum() == 0:
        return 0.5
    best_t, best_f = 0.5, -1.0
    for t in np.unique(np.round(p, 3)):
        pred = p >= t
        tp = float(np.sum(pred & (y == 1)))
        fp = float(np.sum(pred & (y == 0)))
        fn = float(np.sum(~pred & (y == 1)))
        f = 2 * tp / (2 * tp + fp + fn) if tp > 0 else 0.0
        if f > best_f:
            best_f, best_t = f, float(t)
    return best_t


class FittedModel:
    """A model fit on one training window."""

    def __init__(self, spec: ModelSpec, h: int, seed: int = 42) -> None:
        self.spec = spec
        self.h = h
        self.seed = seed
        self.features: list[str] = []
        self.dropped_features: list[str] = []
        self.params: dict[str, Any] = {}
        self.estimator: BaseEstimator | None = None
        self.constant: float | None = None
        self.decision_threshold: float = 0.5
        self.train_rows = 0

    def fit(self, train: pd.DataFrame, target: str) -> FittedModel:
        y = train[target].to_numpy(dtype=float)
        self.train_rows = len(train)
        s = self.spec
        if s.estimator in ("naive", "seasonal_naive"):
            return self
        if s.estimator == "climatology":
            self.constant = float(np.mean(y)) if len(y) else float("nan")
            self.decision_threshold = 0.5
            return self
        assert s.family is not None
        cols = family_features(s.family, self.h)
        miss = train[cols].isna().mean()
        self.features = [c for c in cols if miss[c] <= MAX_MISSING_SHARE]
        self.dropped_features = [c for c in cols if c not in self.features]
        X = train[self.features]
        self.params, val_y, val_p = self._select(train, X, y)
        self.estimator = _make_estimator(s, self.params, self.seed)
        if s.task == "classification" and len(np.unique(y)) < 2:
            self.estimator = None
            self.constant = float(np.mean(y))
            return self
        self.estimator.fit(X, y)  # type: ignore[attr-defined]
        if s.task == "classification":
            self.decision_threshold = best_f1_threshold(val_y, val_p) if len(val_y) else 0.5
        return self

    def _select(
        self, train: pd.DataFrame, X: pd.DataFrame, y: np.ndarray
    ) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
        grid = self.spec.grid or [{}]
        origins = train["origin"]
        val_start = origins.max() - pd.DateOffset(months=INNER_VALIDATION_MONTHS - 1)
        inner_tr = (origins + pd.DateOffset(months=self.h)) <= val_start  # purge: targets realised
        inner_va = origins >= val_start
        empty = np.array([])
        if inner_tr.sum() < 30 or inner_va.sum() < 10 or len(grid) == 1:
            return grid[0], empty, empty
        if self.spec.task == "classification" and len(np.unique(y[inner_tr.to_numpy()])) < 2:
            return grid[0], empty, empty
        loss = _loss(self.spec.task)
        best, best_loss, best_pred = grid[0], np.inf, empty
        for params in grid:
            est = _make_estimator(self.spec, params, self.seed)
            est.fit(X[inner_tr.to_numpy()], y[inner_tr.to_numpy()])  # type: ignore[attr-defined]
            p = _predict(est, self.spec.task, X[inner_va.to_numpy()])
            ls = loss(y[inner_va.to_numpy()], p)
            if ls < best_loss:
                best, best_loss, best_pred = params, ls, p
        return best, y[inner_va.to_numpy()], best_pred

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        s = self.spec
        if s.estimator == "naive":
            return np.zeros(len(rows))
        if s.estimator == "seasonal_naive":
            return rows[f"seasonal_naive_h{self.h}"].to_numpy(dtype=float)
        if self.estimator is None:
            return np.full(len(rows), self.constant if self.constant is not None else np.nan)
        return _predict(self.estimator, s.task, rows[self.features])

    def coefficients(self) -> dict[str, float] | None:
        """Standardised coefficients (per 1 s.d. of the training-window feature)."""
        if not isinstance(self.estimator, Pipeline):
            return None
        m = self.estimator.named_steps["model"]
        coef = np.ravel(m.coef_)
        return {f: float(c) for f, c in zip(self.features, coef, strict=True)}
