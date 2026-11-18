"""Exercise 6: the country-balanced loss used by the Forecastability Atlas.

See docs/RESEARCH_DESIGN_EXPLAINED.md, section 3.
"""

import pandas as pd


def country_balanced_loss(losses: pd.DataFrame) -> float:
    """Average squared errors so that every country present in a month has equal weight.

    ``losses`` has columns ``country``, ``month``, ``series`` and ``loss``. Average ``loss`` over
    series within each (country, month), then over countries within each month, then over months.
    Rows with a missing loss are ignored. Raise ``ValueError`` if no finite loss remains.
    """
    raise NotImplementedError
