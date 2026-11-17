"""External data providers and the registry that builds them from settings."""

from __future__ import annotations

from market_almanac.config import Settings
from market_almanac.http import HttpClient, HttpConfig
from market_almanac.providers.base import Provider
from market_almanac.providers.faostat import FaostatProvider
from market_almanac.providers.hdx_hapi import HdxHapiProvider
from market_almanac.providers.imf import ImfProvider
from market_almanac.providers.nasa_power import NasaPowerProvider
from market_almanac.providers.world_bank import WorldBankProvider

PROVIDER_IDS = ("hdx_hapi", "nasa_power", "world_bank", "imf", "faostat")
PROVIDER_CLASSES = {
    "hdx_hapi": HdxHapiProvider,
    "nasa_power": NasaPowerProvider,
    "world_bank": WorldBankProvider,
    "imf": ImfProvider,
    "faostat": FaostatProvider,
}


def http_from_settings(settings: Settings, transport=None) -> HttpClient:  # type: ignore[no-untyped-def]
    return HttpClient(
        HttpConfig(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            backoff_base_seconds=settings.http_backoff_base_seconds,
            max_concurrency=settings.http_max_concurrency,
            cache_dir=settings.cache_dir,
            cache_ttl_seconds=settings.http_cache_ttl_hours * 3600,
        ),
        transport=transport,
    )


def build_providers(settings: Settings, http: HttpClient | None = None) -> dict[str, Provider]:
    http = http or http_from_settings(settings)
    return {
        "hdx_hapi": HdxHapiProvider(http, settings),
        "nasa_power": NasaPowerProvider(http),
        "world_bank": WorldBankProvider(http),
        "imf": ImfProvider(http),
        "faostat": FaostatProvider(http, settings),
    }
