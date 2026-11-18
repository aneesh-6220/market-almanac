#!/usr/bin/env python3
"""Measure latency (and, in-process, peak memory) of the global price endpoints.

    # in-process over a local data directory (fresh interpreter, peak RSS reported)
    python scripts/ops/benchmark_global_prices.py --data-dir data

    # a running deployment (latency only; memory comes from the host's metrics)
    python scripts/ops/benchmark_global_prices.py --url https://market-almanac.onrender.com

The workload is a visitor's browse: country list, then for ten countries (the largest included) the markets,
the series page, one series, its observations and the CSV export. Output is one JSON document.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from typing import Any

COUNTRIES = ["SYR", "IDN", "ETH", "HTI", "NPL", "ARM", "TCD", "AFG", "COD", "SOM"]


def _percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def run(get: Any, rounds: int, concurrency: int = 1) -> dict[str, Any]:
    """Run the browse workload; with ``concurrency`` > 1 that many visitors browse at the same time."""
    lat: dict[str, list[float]] = {}
    errors: list[str] = []

    def call(label: str, url: str, **params: Any) -> Any:
        t = time.perf_counter()
        r = get(url, params=params)
        lat.setdefault(label, []).append((time.perf_counter() - t) * 1000)
        if r.status_code != 200:
            errors.append(f"{url} -> {r.status_code}: {r.text[:120]}")
            raise RuntimeError(errors[-1])
        return r

    def visitor() -> None:
        for _ in range(rounds):
            call("countries", "/api/v1/global/countries")
            for iso in COUNTRIES:
                call("markets", f"/api/v1/global/countries/{iso}/markets")
                call("commodities", f"/api/v1/global/countries/{iso}/commodities")
                page = call(
                    "series_page", f"/api/v1/global/countries/{iso}/series", limit=50, sort="observations"
                ).json()
                sid = page["items"][0]["series_id"]
                call("series_detail", f"/api/v1/global/series/{sid}")
                call("observations", f"/api/v1/global/series/{sid}/observations", limit=500)
                call("history", f"/api/v1/series/{sid}/history")
                call("export_csv", f"/api/v1/global/series/{sid}/export", format="csv")

    if concurrency <= 1:
        visitor()
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for f in [pool.submit(visitor) for _ in range(concurrency)]:
                f.result()
    out = {
        k: {
            "n": len(v),
            "p50_ms": round(_percentile(v, 0.5), 1),
            "p95_ms": round(_percentile(v, 0.95), 1),
            "max_ms": round(max(v), 1),
        }
        for k, v in lat.items()
    }
    allv = [x for v in lat.values() for x in v]
    out["_all"] = {
        "n": len(allv),
        "p50_ms": round(_percentile(allv, 0.5), 1),
        "p95_ms": round(_percentile(allv, 0.95), 1),
        "max_ms": round(max(allv), 1),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", help="local data directory holding the installed price artefact")
    ap.add_argument("--url", help="base URL of a running API")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=1, help="simultaneous visitors (default 1)")
    a = ap.parse_args()
    if bool(a.data_dir) == bool(a.url):
        ap.error("give exactly one of --data-dir or --url")
    if a.url:
        import httpx

        with httpx.Client(base_url=a.url.rstrip("/"), timeout=120, follow_redirects=True) as c:
            t0 = time.perf_counter()
            first = c.get("/api/v1/global/countries")
            result = {
                "target": a.url,
                "first_request_ms": round((time.perf_counter() - t0) * 1000),
                "first_status": first.status_code,
            }
            result["latency"] = run(c.get, a.rounds, a.concurrency)
        print(json.dumps(result, indent=2))
        return
    import tempfile

    tmp = tempfile.mkdtemp()
    os.environ.update(
        DATA_DIR=os.path.abspath(a.data_dir),
        MARKET_ALMANAC_MODE="live",
        GLOBAL_PRICES_AUTO_INSTALL="0",
        DATABASE_URL=f"sqlite:///{tmp}/bench.db",
        CACHE_DIR=f"{tmp}/cache",
        API_RATE_LIMIT_PER_MINUTE="1000000",
    )
    import logging

    from fastapi.testclient import TestClient

    from market_almanac.config import get_settings
    from market_almanac.services import init_db
    from market_almanac_api.main import create_app

    logging.disable(logging.CRITICAL)
    init_db(get_settings())
    client = TestClient(create_app())
    base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    result = {
        "target": "in-process",
        "rss_after_import_mb": round(base / divisor, 1),
        "latency": run(client.get, a.rounds, a.concurrency),
    }
    result["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor, 1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
