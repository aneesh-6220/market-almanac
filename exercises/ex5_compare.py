"""Exercise 5: when may price series be compared?"""

from typing import Any


def comparability(meta: list[dict[str, Any]]) -> str:
    """Return "invalid", "indexed_only" or "absolute_and_indexed".

    Each item has commodity_name, price_type, unit and currency. Fewer than 2 series is "invalid".
    Any difference in commodity_name, price_type or unit (ignoring case and surrounding whitespace)
    is "invalid". Otherwise, different currencies give "indexed_only"; one currency gives
    "absolute_and_indexed".
    """
    raise NotImplementedError
