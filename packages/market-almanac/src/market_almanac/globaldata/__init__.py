"""Global data foundation: discovery, country-partitioned ingestion, QC and the coverage registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def global_dir(settings: Any) -> Path:
    """Run logs, discovery records and registries (small JSON; separate from the Parquet lake)."""
    return Path(settings.data_dir) / "global" / settings.market_almanac_mode.value
