import numpy as np
import pytest

from exercises.ex3_newey_west import long_run_variance


def test_lag_zero_is_population_variance():
    d = np.array([0.02, -0.01, 0.03, 0.0])
    assert long_run_variance(d, 0) == pytest.approx(np.var(d))


def test_worked_example_from_the_guide():
    d = np.array([0.02, -0.01, 0.03, 0.0])
    assert long_run_variance(d, 1) == pytest.approx(5e-5)


def test_positive_on_random_data():
    rng = np.random.default_rng(2)
    for _ in range(20):
        assert long_run_variance(rng.normal(size=60), 3) > 0
