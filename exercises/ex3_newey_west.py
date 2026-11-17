"""Exercise 3: Newey-West (Bartlett) long-run variance."""

import numpy as np


def long_run_variance(d: np.ndarray, lags: int) -> float:
    """gamma_0 + 2 * sum_{k=1..lags} (1 - k/(lags+1)) * gamma_k, with gamma_k = sum(dc[k:] * dc[:-k]) / T
    and dc = d - mean(d). Note the divisor T (not T - k)."""
    raise NotImplementedError
