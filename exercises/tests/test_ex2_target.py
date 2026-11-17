import numpy as np
import pandas as pd
import pytest

from exercises.ex2_target import log_change_target

IDX = pd.date_range("2026-01-01", periods=12, freq="MS")


def test_known_value():
    p = pd.Series(np.arange(100.0, 112.0), index=IDX)
    p.iloc[9], p.iloc[11] = 300.0, 330.0  # October and December
    y = log_change_target(p, h=1, lag=1)
    assert y.iloc[10] == pytest.approx(np.log(330 / 300))  # origin November


def test_prices_between_known_and_target_do_not_matter():
    rng = np.random.default_rng(1)
    p = pd.Series(rng.uniform(100, 200, 12), index=IDX)
    h, lag, t = 3, 1, 5
    base = log_change_target(p, h, lag).iloc[t]
    q = p.copy()
    q.iloc[t - lag + 1 : t + h] *= 1.5
    assert log_change_target(q, h, lag).iloc[t] == pytest.approx(base)


def test_non_positive_and_bad_arguments():
    p = pd.Series(np.full(12, 100.0), index=IDX)
    p.iloc[4] = 0.0
    assert np.isnan(log_change_target(p, 1, 0).iloc[3])
    with pytest.raises(ValueError):
        log_change_target(p, 0, 0)
    with pytest.raises(ValueError):
        log_change_target(p, 1, -1)
