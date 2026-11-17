"""Exercise 2: a leakage-safe forecast target."""

import pandas as pd


def log_change_target(price: pd.Series, h: int, lag: int) -> pd.Series:
    """ln P(t+h) - ln P(t-lag) for each month t of a consecutive monthly series.

    Non-positive or missing prices give NaN. Raise ValueError if h < 1 or lag < 0.
    """
    raise NotImplementedError
