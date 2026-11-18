import numpy as np
import pandas as pd
import pytest

from exercises.ex6_country_balance import country_balanced_loss


def frame(rows):
    return pd.DataFrame(rows, columns=["country", "month", "series", "loss"])


def test_big_country_does_not_dominate():
    # month 1: country A has 3 series with loss 1, country B 1 series with loss 5 -> (1 + 5) / 2 = 3
    rows = [("A", 1, f"a{i}", 1.0) for i in range(3)] + [("B", 1, "b0", 5.0)]
    assert country_balanced_loss(frame(rows)) == pytest.approx(3.0)


def test_months_then_countries():
    rows = [("A", 1, "a", 2.0), ("B", 1, "b", 4.0), ("A", 2, "a", 6.0)]
    # month 1 -> 3, month 2 -> 6 (only A present), overall 4.5
    assert country_balanced_loss(frame(rows)) == pytest.approx(4.5)


def test_missing_ignored_and_empty_rejected():
    rows = [("A", 1, "a", 2.0), ("A", 1, "b", np.nan)]
    assert country_balanced_loss(frame(rows)) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        country_balanced_loss(frame([("A", 1, "a", np.nan)]))
