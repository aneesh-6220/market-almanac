"""Keep the API inside a small host's memory (Render Free: 512 MiB, about 0.1 vCPU).

Three measures, all process-wide and cheap:

* ``limit_malloc_arenas`` caps glibc's per-thread heaps. Request threads otherwise each grow their own arena and the
  resident size ratchets up after every burst even though Python has freed the objects.
* ``release_heap`` returns freed pages to the OS (``malloc_trim``), at most once every few seconds.
* ``ConcurrencyGate`` (in ``main``) lets only a few data requests execute at once; the rest wait in the event loop.

All of it is a no-op where glibc is absent (macOS, musl), so development and tests are unaffected.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

M_ARENA_MAX = -8  # mallopt parameter number (glibc malloc.h)
TRIM_INTERVAL_SECONDS = 3.0


def _libc() -> Any:
    try:
        return ctypes.CDLL("libc.so.6")
    except OSError:
        return None


_LIBC = _libc()
_last_trim = 0.0


def limit_malloc_arenas(max_arenas: int = 2) -> bool:
    """Cap the number of glibc malloc arenas. Call before worker threads exist. Returns whether it took effect."""
    if _LIBC is None:
        return False
    try:
        return bool(_LIBC.mallopt(M_ARENA_MAX, max_arenas))
    except AttributeError:
        return False


def release_heap(now: float | None = None) -> bool:
    """Give freed heap pages back to the OS, at most once per ``TRIM_INTERVAL_SECONDS``. Returns whether it ran."""
    global _last_trim
    if _LIBC is None:
        return False
    t = time.monotonic() if now is None else now
    if t - _last_trim < TRIM_INTERVAL_SECONDS:
        return False
    _last_trim = t
    try:
        _LIBC.malloc_trim(0)
    except AttributeError:
        return False
    return True


def rss_mb() -> tuple[float, float] | None:
    """(current, peak) resident memory of this process in MB from /proc (Linux), else None."""
    try:
        fields = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value = line.split(":", 1)
                fields[key] = float(value.split()[0]) / 1024
        return fields["VmRSS"], fields["VmHWM"]
    except (OSError, KeyError, ValueError):
        return None


def start_memory_watch(
    inflight: Callable[[], dict[str, int]],
    emit: Callable[..., None],
    threshold_mb: float = 380.0,
    interval_seconds: float = 1.0,
) -> threading.Thread | None:
    """Log when resident memory is high, with the requests in flight, so an out-of-memory kill is explainable.

    Sampling is one /proc read per second; nothing is logged while memory is below ``threshold_mb``. A no-op where
    /proc is not available.
    """
    if rss_mb() is None:
        return None

    def run() -> None:
        while True:
            time.sleep(interval_seconds)
            sample = rss_mb()
            if sample and sample[0] >= threshold_mb:
                emit("memory high", rss_mb=round(sample[0]), peak_mb=round(sample[1]), inflight=inflight())

    t = threading.Thread(target=run, name="memory-watch", daemon=True)
    t.start()
    return t
