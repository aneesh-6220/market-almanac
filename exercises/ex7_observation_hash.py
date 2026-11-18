"""Exercise 7: a content hash that detects real changes and ignores retrieval noise.

See docs/adr/0001-country-partitioned-lake.md.
"""

import pandas as pd


def observation_hash(prices: pd.DataFrame, ignore: tuple[str, ...] = ("retrieved_at",)) -> str:
    """Return a SHA-256 hex digest of the observations that is independent of row and column order.

    Drop the ``ignore`` columns, sort the columns by name and the rows by every remaining column,
    serialise the result deterministically (for example ``to_csv(index=False)``) and hash the bytes.
    Two downloads with the same observations but different ``retrieved_at`` must hash equal; any
    change in a price, period or market must change the hash.
    """
    raise NotImplementedError
