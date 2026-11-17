import numpy as np
import pytest

from exercises.ex1_holm import holm


def test_hand_computed():
    assert holm([0.01, 0.04, 0.02]) == pytest.approx([0.03, 0.04, 0.04])


def test_capped_and_monotone_in_sorted_order():
    p = [0.5, 0.2, 0.9, 0.01]
    adj = holm(p)
    order = np.argsort(p)
    assert all(0 <= a <= 1 for a in adj)
    assert all(adj[order[i]] <= adj[order[i + 1]] + 1e-12 for i in range(len(p) - 1))


def test_matches_statsmodels():
    from statsmodels.stats.multitest import multipletests

    rng = np.random.default_rng(0)
    for _ in range(50):
        p = rng.uniform(0, 1, rng.integers(1, 12)).tolist()
        assert holm(p) == pytest.approx(list(multipletests(p, method="holm")[1]))
