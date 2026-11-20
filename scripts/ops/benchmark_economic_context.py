"""Memory and latency of investigations with and without the economic context (local; no network, no production DB).

    DATA_DIR=<dir with lake/ public/ and optionally context/> uv run python scripts/ops/benchmark_economic_context.py \
        [--n 40] [--no-context]

Reports resident memory (RSS) at start, after the first request and after N distinct investigations, request
latency percentiles, and the size of the context snapshot on disk. It uses an isolated SQLite file, never the
configured DATABASE_URL, and the API's in-process test client, so it measures the application, not the network.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def rss_mb() -> float:
    import resource

    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1e6 if sys.platform == "darwin" else r / 1e3


def current_rss_mb() -> float:
    """Resident set size now, from ``ps`` (no extra dependency); ``ru_maxrss`` alone only ever rises."""
    import subprocess

    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, check=True)
    return int(out.stdout.strip()) / 1e3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--no-context", action="store_true")
    a = ap.parse_args()
    data = Path(os.environ["DATA_DIR"])
    from tests.global_support import deployment

    ctx_dir = data / "context" / "live"
    size = (
        sum(f.stat().st_size for d in ctx_dir.glob("*") if d.is_dir() for f in d.iterdir()) if ctx_dir.is_dir() else 0
    )
    with deployment(data, Path(tempfile.mkdtemp())) as c:
        if a.no_context:
            from market_almanac_api import deps

            deps.economic_context_snapshot = lambda: (None, {"status": "not_installed", "reason": "benchmark"})  # type: ignore[assignment]
            import market_almanac_api.routers.investigations as inv

            inv.economic_context_snapshot = deps.economic_context_snapshot  # type: ignore[attr-defined]
        start = current_rss_mb()
        page = c.get(
            "/api/v1/shocks", params={"limit": 100, "kind": "unusual", "direction": "up", "sort": "recent"}
        ).json()
        items = page["items"][: a.n]
        lat: list[float] = []
        first = None
        for it in items:
            t = time.perf_counter()
            r = c.get(f"/api/v1/investigations/{it['series_id']}", params={"event": it["peak"][:7]})
            dt = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                print("skip", it["series_id"], r.status_code)
                continue
            lat.append(dt)
            if first is None:
                first = current_rss_mb()
        lat.sort()
        p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]  # noqa: E731
        print(
            {
                "context": not a.no_context,
                "snapshot_disk_mb": round(size / 1e6, 2),
                "n": len(lat),
                "rss_start_mb": round(start),
                "rss_after_first_mb": round(first or 0),
                "rss_end_mb": round(current_rss_mb()),
                "peak_rss_mb": round(rss_mb()),
                "latency_ms": {
                    "first": round(lat[0]) if lat else None,
                    "p50": round(statistics.median(lat)),
                    "p95": round(p(0.95)),
                    "max": round(lat[-1]),
                },
            }
        )


if __name__ == "__main__":
    main()
