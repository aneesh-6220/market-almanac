#!/usr/bin/env python3
"""Market-page load times against a locally run API throttled like the Render free tier (a CPU quota, not a laptop).

The free tier gives the API a small CFS quota (about 0.1 vCPU). This starts the real server (``uvicorn``, real data,
the same middleware) and duty-cycles it with SIGSTOP/SIGCONT, which is how ``cpulimit`` imitates a quota, so the
time a page takes here is dominated by CPU cost the way it is in production. ``--duty`` is the fraction of each
100 ms period the process may run: calibrate it so the *old* code reproduces a production timing you measured, then
compare code versions at that setting (see docs/PERFORMANCE.md).

    python scripts/ops/benchmark_throttled.py --duty 0.05 --visitors 2 --rounds 3
    PYTHONPATH=<old checkout>/packages/market-almanac/src:<old checkout>/apps/api/src python ... (an older revision)

A visitor mimics the browser: the primary requests together (status, detail, global detail, history, movement), then
the secondary ones (brief, seasonality, environment, observations). ``--flat`` sends all at once, as the old client did.
Writes JSON to stdout; progress to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = [
    "/api/v1/status",
    "/api/v1/series/{s}",
    "/api/v1/global/series/{s}",
    "/api/v1/series/{s}/history",
    "/api/v1/series/{s}/movement",
]
SECONDARY = [
    "/api/v1/series/{s}/brief",
    "/api/v1/series/{s}/seasonality",
    "/api/v1/series/{s}/environment?months=120",
    "/api/v1/global/series/{s}/observations?limit=100",
]


class Throttle(threading.Thread):
    """Let the process run ``duty`` of every ``period`` seconds."""

    def __init__(self, pid: int, duty: float, period: float = 0.1) -> None:
        super().__init__(daemon=True)
        self.pid, self.on, self.off, self.stop_flag = pid, duty * period, (1 - duty) * period, False

    def run(self) -> None:
        while not self.stop_flag:
            try:
                os.kill(self.pid, signal.SIGCONT)
                time.sleep(self.on)
                os.kill(self.pid, signal.SIGSTOP)
                time.sleep(self.off)
            except ProcessLookupError:
                return


def rss_mb(pid: int) -> float:
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)])) / 1024


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duty", type=float, default=0.05)
    ap.add_argument("--visitors", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--countries", default="ARM,ETH,NPL,TCD,HTI")
    ap.add_argument("--flat", action="store_true", help="send every request at once (the pre-1.2.1 client)")
    ap.add_argument("--gate", type=int, default=3, help="API_MAX_CONCURRENT_REQUESTS")
    ap.add_argument("--label", default="run")
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()

    tmp = tempfile.mkdtemp()
    port = 8700 + os.getpid() % 90
    env = dict(
        os.environ,
        DATA_DIR=str(ROOT / "data"),
        MARKET_ALMANAC_MODE="live",
        GLOBAL_PRICES_AUTO_INSTALL="0",
        DATABASE_URL=f"sqlite:///{tmp}/b.db",
        CACHE_DIR=f"{tmp}/cache",
        API_RATE_LIMIT_PER_MINUTE="100000000",
        API_MAX_CONCURRENT_REQUESTS=str(a.gate),
    )
    subprocess.run([str(ROOT / ".venv/bin/market-almanac"), "db-init"], env=env, capture_output=True, check=True)
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/uvicorn"), "market_almanac_api.main:app", "--port", str(port), "--log-level", "warning"],
        env=env,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(240):
            try:
                if httpx.get(base + "/ready", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        ids = []
        with httpx.Client(timeout=60) as c:
            for iso in a.countries.split(","):
                r = c.get(f"{base}/api/v1/global/countries/{iso}/series", params={"limit": 1, "sort": "observations"})
                ids.append(r.json()["items"][0]["series_id"])
        throttle = Throttle(server.pid, a.duty)
        throttle.start()
        peak = [rss_mb(server.pid)]
        stop = threading.Event()

        def sample() -> None:
            while not stop.is_set():
                peak[0] = max(peak[0], rss_mb(server.pid))
                time.sleep(0.2)

        threading.Thread(target=sample, daemon=True).start()
        client = httpx.Client(timeout=a.timeout, limits=httpx.Limits(max_connections=64), http2=False)

        def visit(sid: str) -> dict:
            t0 = time.perf_counter()
            codes: list[int] = []
            waves = [PRIMARY + SECONDARY] if a.flat else [PRIMARY, SECONDARY]
            for wave in waves:
                with ThreadPoolExecutor(len(wave)) as pool:
                    codes += list(pool.map(lambda p: client.get(base + p.format(s=sid)).status_code, wave))
            return {"seconds": round(time.perf_counter() - t0, 2), "non200": [x for x in codes if x != 200]}

        rounds = []
        for r in range(a.rounds):
            picks = [ids[(r + i) % len(ids)] for i in range(a.visitors)]
            with ThreadPoolExecutor(a.visitors) as pool:
                res = list(pool.map(visit, picks))
            rounds.append(res)
            print(
                f"round {r + 1}: "
                + " | ".join(f"{x['seconds']}s" + (f" non200={x['non200']}" if x["non200"] else "") for x in res),
                file=sys.stderr,
            )
        stop.set()
        times = [x["seconds"] for rr in rounds for x in rr]
        print(
            json.dumps(
                {
                    "label": a.label,
                    "duty": a.duty,
                    "visitors": a.visitors,
                    "flat": a.flat,
                    "gate": a.gate,
                    "first_round_s": [x["seconds"] for x in rounds[0]],
                    "median_s": statistics.median(times),
                    "max_s": max(times),
                    "non200": sum(len(x["non200"]) for rr in rounds for x in rr),
                    "peak_rss_mb": round(peak[0]),
                },
                indent=2,
            )
        )
        throttle.stop_flag = True
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(server.pid, signal.SIGCONT)
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(20)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
