#!/usr/bin/env python3
"""Overload a deployed API on purpose and report how it degrades (it must reject, never crash).

    python scripts/ops/overload_test.py --api https://market-almanac.onrender.com --requests 100 --concurrency 100

Sends many heavy requests at once (the legacy pandas endpoints for several countries' series, which are the
expensive ones), without honouring Retry-After, then checks the service is still healthy. Expected on the
free tier: every response is 200, 429 (per-IP rate limit) or 503 + Retry-After (queue timeout); none is a 5xx
without Retry-After, none is a connection error, and /health answers afterwards. Check the host's events and
memory separately (Render: no `server_failed` / `oomKilled`). Keep --requests at or below the per-IP rate limit
(120/min) if you want the gate rather than the limiter to be what is exercised.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

HEAVY = [
    "/api/v1/series/{s}/movement",
    "/api/v1/series/{s}/seasonality",
    "/api/v1/series/{s}/environment?months=120",
    "/api/v1/series/{s}/brief",
    "/api/v1/series/{s}/history",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--requests", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--countries", default="ARM,ETH,NPL,TCD,HTI")
    ap.add_argument("--timeout", type=float, default=90)
    a = ap.parse_args()
    api = a.api.rstrip("/")
    with httpx.Client(timeout=60) as c:
        ids = [
            c.get(f"{api}/api/v1/global/countries/{i}/series", params={"limit": 3, "sort": "observations"}).json()[
                "items"
            ]
            for i in a.countries.split(",")
        ]
    sids = [x["series_id"] for items in ids for x in items]
    urls = [api + HEAVY[i % len(HEAVY)].format(s=sids[i % len(sids)]) for i in range(a.requests)]

    def hit(u: str) -> dict:
        t = time.perf_counter()
        try:
            r = httpx.get(u, timeout=a.timeout)
            return {"status": r.status_code, "retry_after": r.headers.get("retry-after"), "s": time.perf_counter() - t}
        except httpx.HTTPError as e:
            return {"status": type(e).__name__, "retry_after": None, "s": time.perf_counter() - t}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as pool:
        res = list(pool.map(hit, urls))
    wall = time.perf_counter() - t0
    codes = collections.Counter(str(r["status"]) for r in res)
    bad = [r for r in res if r["status"] not in (200, 429, 503) or (r["status"] == 503 and not r["retry_after"])]
    ok_times = [r["s"] for r in res if r["status"] == 200]
    health = None
    for _ in range(30):
        try:
            health = httpx.get(api + "/health", timeout=20).json()
            break
        except httpx.HTTPError:
            time.sleep(2)
    print(
        json.dumps(
            {
                "requests": a.requests,
                "concurrency": a.concurrency,
                "wall_s": round(wall, 1),
                "status_counts": dict(codes),
                "unbounded_failures": len(bad),
                "ok_median_s": round(statistics.median(ok_times), 1) if ok_times else None,
                "ok_max_s": round(max(ok_times), 1) if ok_times else None,
                "health_after": health,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
