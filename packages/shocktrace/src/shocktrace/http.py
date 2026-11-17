"""Shared, hardened HTTP access for data providers.

Features: per-host allow-list (no arbitrary outbound URLs), bounded concurrency,
timeouts, exponential backoff with jitter, ``Retry-After`` support, and an on-disk
response cache keyed on the *redacted* request so credentials never land in cache keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from shocktrace.logging import get_logger, log_event, redact

log = get_logger("http")

ALLOWED_HOSTS = frozenset(
    {
        "hapi.humdata.org",
        "power.larc.nasa.gov",
        "api.worldbank.org",
        "api.imf.org",
        "faostatservices.fao.org",
        "bulks-faostat.fao.org",
    }
)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ProviderHTTPError(Exception):
    """Raised when a provider request fails after retries. Message is safe to display."""

    def __init__(self, message: str, status_code: int | None = None, retryable: bool = False):
        super().__init__(redact(message))
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class HttpConfig:
    timeout_seconds: float = 60.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    max_concurrency: int = 4
    cache_dir: Path | None = None
    cache_ttl_seconds: float = 24 * 3600
    user_agent: str = "ShockTrace/0.1 (+https://github.com/shocktrace/shocktrace)"


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return None


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff: U(0, min(cap, base * 2**attempt))."""
    r = rng or random
    return r.uniform(0, min(cap, base * (2**attempt)))


class HttpClient:
    """Async HTTP client shared by providers.

    ``secret_params``/``secret_headers`` are sent on the wire but excluded from cache keys
    and logs.
    """

    def __init__(
        self,
        config: HttpConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.config = config or HttpConfig()
        self._transport = transport
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self.request_count = 0

    def _check_host(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise ProviderHTTPError(f"Outbound host not allowed: {host}")

    def _cache_path(self, method: str, url: str, params: dict[str, Any] | None, body: Any) -> Path | None:
        if self.config.cache_dir is None:
            return None
        key_src = json.dumps(
            {"m": method, "u": url, "p": sorted((params or {}).items()), "b": body},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(key_src.encode()).hexdigest()
        host = urlparse(url).hostname or "unknown"
        return self.config.cache_dir / "http" / host / f"{digest}.json"

    def _read_cache(self, path: Path | None) -> dict[str, Any] | None:
        if path is None or not path.exists():
            return None
        try:
            entry = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - entry.get("stored_at", 0) > self.config.cache_ttl_seconds:
            return None
        return entry

    def _write_cache(self, path: Path | None, status: int, text: str, headers: dict[str, str]) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stored_at": time.time(), "status": status, "text": text, "headers": headers}))
        tmp.replace(path)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        secret_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        secret_headers: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> CachedResponse:
        self._check_host(url)
        cache_path = self._cache_path(method, url, params, data if method != "POST" else "post")
        if use_cache and method == "GET":
            hit = self._read_cache(cache_path)
            if hit is not None:
                return CachedResponse(hit["status"], hit["text"], hit.get("headers", {}), from_cache=True)

        all_params = {**(params or {}), **(secret_params or {})}
        all_headers = {"User-Agent": self.config.user_agent, **(headers or {}), **(secret_headers or {})}
        display_url = f"{url}?{urlencode(params or {})}" if params else url
        last_exc: Exception | None = None
        async with (
            self._semaphore,
            httpx.AsyncClient(
                timeout=self.config.timeout_seconds, transport=self._transport, follow_redirects=True
            ) as client,
        ):
            for attempt in range(self.config.max_retries + 1):
                try:
                    self.request_count += 1
                    resp = await client.request(method, url, params=all_params or None, headers=all_headers, data=data)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_exc = exc
                    delay = backoff_delay(attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds)
                    log_event(
                        log,
                        "http transport error; retrying",
                        url=display_url,
                        attempt=attempt,
                        error=type(exc).__name__,
                        delay=round(delay, 2),
                    )
                    if attempt < self.config.max_retries:
                        await self._sleep(delay)
                        continue
                    raise ProviderHTTPError(
                        f"Network error contacting {urlparse(url).hostname}: {type(exc).__name__}",
                        retryable=True,
                    ) from exc

                if resp.status_code in RETRYABLE_STATUS and attempt < self.config.max_retries:
                    ra = parse_retry_after(resp.headers.get("Retry-After"))
                    delay = (
                        ra
                        if ra is not None
                        else backoff_delay(attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds)
                    )
                    delay = min(delay, self.config.backoff_max_seconds)
                    log_event(
                        log,
                        "retryable status; backing off",
                        url=display_url,
                        status=resp.status_code,
                        attempt=attempt,
                        delay=round(delay, 2),
                    )
                    await self._sleep(delay)
                    continue
                if resp.status_code >= 400:
                    raise ProviderHTTPError(
                        f"{urlparse(url).hostname} returned HTTP {resp.status_code}",
                        status_code=resp.status_code,
                        retryable=resp.status_code in RETRYABLE_STATUS,
                    )
                text = resp.text
                hdrs = {k: v for k, v in resp.headers.items() if k.lower() in {"content-type", "last-modified", "date"}}
                if use_cache and method == "GET":
                    self._write_cache(cache_path, resp.status_code, text, hdrs)
                return CachedResponse(resp.status_code, text, hdrs, from_cache=False)
        raise ProviderHTTPError(f"Request failed: {last_exc}", retryable=True)

    async def get_json(self, url: str, **kw: Any) -> Any:
        r = await self.request("GET", url, **kw)
        try:
            return json.loads(r.text)
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(f"Malformed JSON from {urlparse(url).hostname}") from exc

    async def get_text(self, url: str, **kw: Any) -> str:
        return (await self.request("GET", url, **kw)).text


@dataclass
class CachedResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    from_cache: bool = False
