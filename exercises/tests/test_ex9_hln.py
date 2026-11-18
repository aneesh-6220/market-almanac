import numpy as np
import pytest

from exercises.ex9_hln import dm_hln
from market_almanac.evaluation.inference import diebold_mariano


def test_matches_the_project_implementation():
    rng = np.random.default_rng(3)
    for h in (1, 3):
        for T in (30, 57, 120):
            d = rng.normal(0.02, 0.1, T)
            ref = diebold_mariano(d, np.zeros(T), dates=np.arange(T), h=h, min_periods=1)  # d = loss_a - loss_b
            stat, p = dm_hln(d, h)
            assert stat == pytest.approx(ref.stat, rel=1e-9)
            assert p == pytest.approx(ref.p_value_b_better, rel=1e-9)


def test_rejects_degenerate_input():
    with pytest.raises(ValueError):
        dm_hln(np.array([0.1, 0.2]), 1)
    with pytest.raises(ValueError):
        dm_hln(np.zeros(20), 1)
