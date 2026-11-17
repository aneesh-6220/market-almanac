"""Real network tests against the official provider endpoints.

Deselected by default (``-m 'not live'``). Run with ``pytest -m live``. Credential-dependent
tests skip when the credential is absent, so ordinary CI never needs secrets.
"""

from __future__ import annotations

from datetime import date

import pytest

from shocktrace.config import Settings
from shocktrace.providers import build_providers
from shocktrace.providers.base import HealthStatus
from tests.conftest import run

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def providers():  # type: ignore[no-untyped-def]
    return build_providers(Settings(http_cache_ttl_hours=0.0))


def test_nasa_power_live(providers):
    res = run(
        providers["nasa_power"].fetch(
            "weather_monthly", lat=-1.29, lon=36.82, start=date(2023, 1, 1), end=date(2023, 12, 31), use_cache=False
        )
    )
    assert len(res.frame) == 12 and res.frame["complete"].all()
    assert res.frame["precip_total_mm"].between(0, 2000).all()


def test_world_bank_live(providers):
    res = run(
        providers["world_bank"].fetch("indicators", country_iso3="KEN", indicators=["SP.POP.TOTL"], start_year=2015)
    )
    assert len(res.frame) >= 5 and (res.frame["value"] > 10_000_000).all()


def test_imf_live(providers):
    res = run(providers["imf"].fetch("macro_monthly", country_iso3="KEN", start_period="2022-01"))
    assert res.extra["series_status"]["IMF.CPI.ALL"] == "ok"
    assert (res.frame["indicator_code"] == "IMF.FX.USD").any()


def test_hdx_hapi_live(providers):
    p = providers["hdx_hapi"]
    if not p.is_configured():
        pytest.skip("HDX_HAPI_APP_IDENTIFIER not set")
    res = run(
        p.fetch(
            "food_prices",
            country_iso3="KEN",
            commodity_code="134",
            start_date="2024-01-01",
            end_date="2024-06-30",
            use_cache=False,
        )
    )
    assert len(res.frame) > 0 and res.frame["series_id"].nunique() > 1


def test_faostat_live(providers):
    p = providers["faostat"]
    if not p.is_configured():
        pytest.skip("FAOSTAT credentials not set or token expired")
    res = run(p.fetch("crop_production", country_iso3="KEN", item_code="56", start_year=2018, end_year=2022))
    assert set(res.frame["element_code"]) == {"5312", "5412", "5510"}


def test_health_checks_live(providers):
    for pid in ("nasa_power", "world_bank", "imf"):
        h = run(providers[pid].health_check())
        assert h.status == HealthStatus.HEALTHY, (pid, h.message)
