import pytest

from exercises.ex4_weighting import weighted_index

W = {"a": 0.5, "b": 0.3, "c": 0.2}


def test_guide_example():
    assert weighted_index({"a": 100, "b": 80, "c": 50}, W) == pytest.approx(84.0)


def test_missing_below_coverage():
    assert weighted_index({"a": 100, "b": None, "c": 50}, W) is None
    assert weighted_index({"a": 100, "b": 80}, W, min_coverage=0.8) == pytest.approx((50 + 24) / 0.8)


def test_order_invariant_and_validation():
    assert weighted_index({"c": 50, "b": 80, "a": 100}, dict(reversed(list(W.items())))) == pytest.approx(84.0)
    with pytest.raises(ValueError):
        weighted_index({"a": 1}, {"a": 0.5, "b": 0.4})
    with pytest.raises(ValueError):
        weighted_index({"a": 1}, {"a": 1.2, "b": -0.2})
