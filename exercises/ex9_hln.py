"""Exercise 9: Diebold–Mariano with the Harvey–Leybourne–Newbold correction.

See docs/RESEARCH_DESIGN_EXPLAINED.md, section 4.
"""

import numpy as np


def dm_hln(d: np.ndarray, h: int) -> tuple[float, float]:
    """Return (statistic, one-sided p-value) for H1: mean(d) > 0.

    ``d`` is the monthly loss difference (baseline minus challenger). Use the Newey–West long-run
    variance with Bartlett weights and lag ``max(h - 1, floor(4 * (T / 100) ** (2 / 9)))``:
    V = g0 + 2 * sum_{k=1..lag} (1 - k / (lag + 1)) * g_k, where g_k is the lag-k autocovariance of
    the demeaned d (divide by T). DM = mean(d) / sqrt(V / T); multiply by
    sqrt((T + 1 - 2h + h(h - 1) / T) / T); p = P(t_{T-1} > statistic).
    Raise ``ValueError`` if T < 3 or V <= 0.
    """
    raise NotImplementedError
