"""Exercise 1: Holm step-down adjusted p-values."""


def holm(p_values: list[float]) -> list[float]:
    """Return Holm-adjusted p-values in the original order.

    Sort ascending p_(1) <= ... <= p_(m); adjusted p_(i) = max_{j<=i} min(1, (m - j + 1) * p_(j)).
    """
    raise NotImplementedError
