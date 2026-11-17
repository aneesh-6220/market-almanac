"""Exercise 4: production-weighted index with a minimum observed-weight rule."""


def weighted_index(
    values: dict[str, float | None], weights: dict[str, float], min_coverage: float = 0.9
) -> float | None:
    """Weighted mean of the observed cells, renormalised by the observed weight.

    Return None when the observed weight is below ``min_coverage``. Raise ValueError if any weight
    is negative or the weights do not sum to 1 (tolerance 1e-6). Cells absent from ``values`` or
    with value None count as missing.
    """
    raise NotImplementedError
