"""Provider adapters tested against recorded *real* responses (data/fixtures/*)."""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import date

import httpx
import numpy as np
import pandas as pd
import pytest
from pydantic import SecretStr

from market_almanac.data.identity import power_grid_cell, weather_location_id
from market_almanac.data.schema import AGRICULTURE, MACRO, PRICES, WEATHER_MONTHLY, validate
from market_almanac.providers.base import (
    HealthStatus,
    ProviderNotConfigured,
    ProviderSchemaError,
)
from market_almanac.providers.faostat import (
    FaostatProvider,
    area_code_for_iso3,
    fao_item_for_commodity,
    jwt_expiry,
    parse_api_rows,
    parse_bulk_zip,
)
from market_almanac.providers.hdx_hapi import PAGE_LIMIT, HdxHapiProvider, normalize_food_prices
from market_almanac.providers.imf import ImfProvider, parse_sdmx_period, parse_structure_specific
from market_almanac.providers.nasa_power import NasaPowerProvider, parse_power_daily
from market_almanac.providers.world_bank import WorldBankProvider, parse_country, parse_indicator_rows
from tests.conftest import fixture_json, fixture_text, run

# ---------------------------------------------------------------- HDX HAPI


def test_hdx_normalize_real_fixture():
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    df, n, _warnings = normalize_food_prices(raw, pd.Timestamp.now(tz="UTC"))
    assert n == len(raw)
    validate(df, PRICES, allow_duplicate_keys=True)
    assert (df["period"].dt.day == 1).all()
    r0 = raw[0]
    first = df[(df.market_code == r0["market_code"])].iloc[0]
    # observation month = calendar month of reference_period_start (WFP's 15th-of-month date)
    assert first["period"] == pd.Timestamp(r0["reference_period_start"][:7] + "-01")
    assert set(df["unit"]) <= {r["unit"] for r in raw}
    assert df["published_at"].isna().all()  # HAPI gives no publication date: never invented
    assert df["source_ref"].str.startswith("hdx:").all()


def test_hdx_schema_change_detected():
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    broken = [{k: v for k, v in r.items() if k != "unit"} for r in raw]
    with pytest.raises(ProviderSchemaError):
        normalize_food_prices(broken, pd.Timestamp.now(tz="UTC"))


def test_hdx_conflicting_duplicates_flagged_not_averaged():
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"][:3]
    dup = dict(raw[0])
    dup["price"] = raw[0]["price"] * 2
    df, _, warnings = normalize_food_prices([*raw, dup, dict(raw[1])], pd.Timestamp.now(tz="UTC"))
    flagged = df[df["quality_flags"].str.contains("duplicate_conflict")]
    assert len(flagged) == 2 and set(flagged["price"]) == {raw[0]["price"], raw[0]["price"] * 2}
    assert any("exact duplicate" in w for w in warnings)


def test_hdx_pagination_and_header_auth(make_http, settings_factory):
    rows = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        off = int(req.url.params["offset"])
        if off == 0:
            # synthesize a full page by repeating the real record shape with distinct markets
            page = [{**rows[i % len(rows)], "market_code": str(i)} for i in range(PAGE_LIMIT)]
            return httpx.Response(200, json={"data": page})
        return httpx.Response(200, json={"data": rows[:5]})

    http, _, _ = make_http(handler)
    p = HdxHapiProvider(http, settings_factory(hdx_hapi_app_identifier=SecretStr("dGVzdDp0ZXN0QGV4YW1wbGUub3Jn")))
    res = run(p.fetch("food_prices", country_iso3="KEN", commodity_code="134"))
    assert len(seen) == 2 and res.raw_record_count == PAGE_LIMIT + 5
    for r in seen:
        assert "app_identifier" not in str(r.url)  # credential sent as header, never in URL
        assert r.headers["X-HDX-HAPI-APP-IDENTIFIER"]


def test_hdx_not_configured(make_http, settings_factory):
    http, rec, _ = make_http(lambda r: httpx.Response(200))
    p = HdxHapiProvider(http, settings_factory())
    h = run(p.health_check())
    assert h.status == HealthStatus.NOT_CONFIGURED and rec.requests == []
    with pytest.raises(ProviderNotConfigured):
        run(p.fetch("food_prices", country_iso3="KEN"))


def test_hdx_input_validation(make_http, settings_factory):
    http, _, _ = make_http(lambda r: httpx.Response(200, json={"data": []}))
    p = HdxHapiProvider(http, settings_factory(hdx_hapi_app_identifier=SecretStr("x")))
    with pytest.raises(ValueError):
        run(p.fetch("food_prices", country_iso3="K3"))
    with pytest.raises(ValueError):
        run(p.fetch("food_prices", country_iso3="KEN", price_type="Retial"))


def test_hdx_unavailable_health(make_http, settings_factory):
    http, _, _ = make_http(lambda r: httpx.Response(500), retries=1)
    p = HdxHapiProvider(http, settings_factory(hdx_hapi_app_identifier=SecretStr("x")))
    h = run(p.health_check())
    assert h.status == HealthStatus.UNAVAILABLE and "500" in h.message


# ---------------------------------------------------------------- NASA POWER


def test_power_parse_real_fixture():
    payload = json.loads(fixture_text("nasa_power", "daily_nairobi_cell_2023q1.json"))
    daily, meta = parse_power_daily(payload)
    assert len(daily) == 90 and meta["time_standard"] == "UTC"
    assert daily["PRECTOTCORR"].notna().all()


def test_power_fill_values_become_missing():
    payload = json.loads(fixture_text("nasa_power", "daily_nairobi_cell_2023q1.json"))
    k = sorted(payload["properties"]["parameter"]["T2M"])[3]
    payload["properties"]["parameter"]["T2M"][k] = -999.0
    daily, meta = parse_power_daily(payload)
    assert np.isnan(daily.loc[3, "T2M"]) and meta["warnings"]


def test_power_unit_change_detected():
    payload = json.loads(fixture_text("nasa_power", "daily_nairobi_cell_2023q1.json"))
    payload["parameters"]["PRECTOTCORR"]["units"] = "kg m-2 s-1"
    with pytest.raises(ProviderSchemaError):
        parse_power_daily(payload)


def test_power_fetch_monthly_and_explicit_time_standard(make_http):
    payload = fixture_text("nasa_power", "daily_nairobi_cell_2023q1.json")
    http, rec, _ = make_http(lambda r: httpx.Response(200, text=payload))
    p = NasaPowerProvider(http, time_standard="UTC")
    res = run(p.fetch("weather_monthly", lat=-1.29, lon=36.82, start=date(2023, 1, 1), end=date(2023, 3, 31)))
    validate(res.frame, WEATHER_MONTHLY)
    assert rec.requests[0].url.params["time-standard"] == "UTC"
    assert len(res.frame) == 3 and res.frame["complete"].all()
    assert "proxy" in res.frame["spatial_basis"].iloc[0]
    with pytest.raises(ValueError):
        NasaPowerProvider(http, time_standard="local")
    with pytest.raises(ValueError):
        run(p.fetch("weather_monthly", lat=0, lon=0, start=date(1970, 1, 1)))


def test_power_grid_dedup():
    assert power_grid_cell(-1.29, 36.82) == power_grid_cell(-1.4, 36.7)
    assert weather_location_id(-1.29, 36.82) != weather_location_id(-1.29, 37.5)
    with pytest.raises(ValueError):
        power_grid_cell(95, 0)


# ---------------------------------------------------------------- World Bank


def test_world_bank_parse_real_fixture():
    payload = fixture_json("world_bank", "ken_fp_cpi_totl_zg.json")
    df = parse_indicator_rows(payload[1], "FP.CPI.TOTL.ZG", payload[0]["lastupdated"])
    assert (df["frequency"] == "A").all() and (df["country_iso3"] == "KEN").all()
    assert len(df) == sum(1 for r in payload[1] if r["value"] is not None)
    assert df["published_at"].isna().all()
    assert "lastupdated" in df["source_ref"].iloc[0]


def test_world_bank_error_payload(make_http):
    err = fixture_text("world_bank", "error_invalid_indicator.json")
    http, _, _ = make_http(lambda r: httpx.Response(200, text=err))
    p = WorldBankProvider(http)
    res = run(p.fetch("indicators", country_iso3="KEN", indicators=["NOT.A.REAL.CODE"]))
    assert res.frame.empty and "unavailable" in res.warnings[0]
    validate(res.frame, MACRO)


def test_world_bank_country():
    df = parse_country(fixture_json("world_bank", "country_ken.json"))
    assert df.iloc[0]["iso3"] == "KEN" and df.iloc[0]["region"]


def test_world_bank_pagination(make_http):
    page1 = [
        {"page": 1, "pages": 2, "per_page": 1, "total": 2, "lastupdated": "2026-01-01"},
        [{"indicator": {"value": "x"}, "countryiso3code": "KEN", "date": "2020", "value": 1.0}],
    ]
    page2 = [
        {"page": 2, "pages": 2, "per_page": 1, "total": 2, "lastupdated": "2026-01-01"},
        [{"indicator": {"value": "x"}, "countryiso3code": "KEN", "date": "2021", "value": None}],
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1 if req.url.params["page"] == "1" else page2)

    http, rec, _ = make_http(handler)
    res = run(WorldBankProvider(http).fetch("indicators", country_iso3="KEN", indicators=["SP.POP.TOTL"]))
    assert len(rec.requests) == 2 and len(res.frame) == 1  # null value is missing, not zero


# ---------------------------------------------------------------- IMF


def test_imf_parse_real_cpi_and_er():
    series, attrs = parse_structure_specific(fixture_text("imf", "cpi_ken_all_2025.xml"))
    assert series and series[0]["attrs"]["COUNTRY"] == "KEN"
    assert "PUBLICATION_DATE" in attrs
    obs = [o for o in series[0]["obs"] if o["value"] is not None]
    assert obs and obs[0]["period"].day == 1
    er, _ = parse_structure_specific(fixture_text("imf", "er_ken_usd_2025.xml"))
    assert er[0]["attrs"]["INDICATOR"] == "XDC_USD"


def test_imf_missing_country_reported_not_substituted(make_http):
    xml = fixture_text("imf", "cpi_missing_country.xml")
    http, _, _ = make_http(lambda r: httpx.Response(200, text=xml))
    res = run(ImfProvider(http).fetch("macro_monthly", country_iso3="XXX", indicators=["IMF.CPI.ALL"]))
    assert res.frame.empty
    assert res.extra["series_status"]["IMF.CPI.ALL"] in ("unavailable", "no_observations")


def test_imf_http_404_is_unavailable(make_http):
    http, _, _ = make_http(lambda r: httpx.Response(404))
    res = run(ImfProvider(http).fetch("macro_monthly", country_iso3="KEN", indicators=["IMF.FX.USD"]))
    assert res.extra["series_status"]["IMF.FX.USD"] == "unavailable"


def test_imf_period_and_malformed():
    assert parse_sdmx_period("2025-M06") == pd.Timestamp("2025-06-01")
    assert parse_sdmx_period("2024") == pd.Timestamp("2024-01-01")
    with pytest.raises(ProviderSchemaError):
        parse_sdmx_period("2024-Q1")
    with pytest.raises(ProviderSchemaError):
        parse_structure_specific("<not xml")


def test_imf_fetch_frame(make_http):
    xml = fixture_text("imf", "cpi_ken_all_2025.xml")
    http, _, _ = make_http(lambda r: httpx.Response(200, text=xml))
    res = run(ImfProvider(http).fetch("macro_monthly", country_iso3="KEN", indicators=["IMF.CPI.ALL"]))
    validate(res.frame, MACRO)
    assert (res.frame["frequency"] == "M").all() and res.frame["published_at"].isna().all()


# ---------------------------------------------------------------- FAOSTAT


def test_faostat_parse_real_fixture():
    rows = fixture_json("faostat", "qcl_ken_maize_2019_2023.json")["data"]
    df = parse_api_rows(rows, "KEN", "faostat:api:QCL:114:56")
    validate(df, AGRICULTURE)
    assert set(df["element_code"]) <= {"5312", "5412", "5510"}
    assert set(df["unit"]) <= {"ha", "kg/ha", "t"}


def _jwt(exp: float) -> str:
    import base64

    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': exp})}.sig"


def test_faostat_token_states(make_http, settings_factory):
    http, rec, _ = make_http(lambda r: httpx.Response(200, json={"data": []}))
    expired = FaostatProvider(http, settings_factory(faostat_access_token=SecretStr(_jwt(time.time() - 10))))
    assert not expired.is_configured() and expired.credential_state() == "token_expired"
    h = run(expired.health_check())
    assert h.status == HealthStatus.NOT_CONFIGURED and rec.requests == []
    with pytest.raises(ProviderNotConfigured, match="bulk"):
        run(expired.fetch("crop_production", country_iso3="KEN", item_code="56"))
    valid = FaostatProvider(http, settings_factory(faostat_access_token=SecretStr(_jwt(time.time() + 3600))))
    assert valid.is_configured()
    assert jwt_expiry("not-a-jwt") is None


def test_faostat_login_flow(make_http, settings_factory):
    tok = _jwt(time.time() + 3600)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth/login"):
            assert req.method == "POST" and b"username=" in req.content
            return httpx.Response(200, json={"AuthenticationResult": {"AccessToken": tok}})
        assert req.headers["Authorization"] == f"Bearer {tok}"
        return httpx.Response(200, json={"data": fixture_json("faostat", "qcl_ken_maize_2019_2023.json")["data"]})

    http, rec, _ = make_http(handler)
    p = FaostatProvider(http, settings_factory(faostat_username="u@example.org", faostat_password=SecretStr("pw")))
    res = run(p.fetch("crop_production", country_iso3="KEN", item_code="56", start_year=2019, end_year=2023))
    assert len(res.frame) > 0
    q = rec.requests[-1].url.params
    assert q["area"] == "114" and q["element"] == "2312,2413,2510"


def test_faostat_bulk_parser(tmp_path):
    csv = (
        '"Area Code","Area Code (M49)","Area","Item Code","Item Code (CPC)","Item","Element Code","Element",'
        '"Year Code","Year","Unit","Value","Flag","Note"\n'
        '"114","\'404","Kenya","56","\'0112","Maize (corn)","5510","Production","2020","2020","t","4000000","A",""\n'
        '"114","\'404","Kenya","56","\'0112","Maize (corn)","5111","Stocks","2020","2020","An","1","A",""\n'
        '"115","\'","Other","56","\'0112","Maize (corn)","5510","Production","2020","2020","t","9","A",""\n'
    )
    z = tmp_path / "q.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Production_Crops_Livestock_E_All_Data_(Normalized).csv", csv)
    df = parse_bulk_zip(z, "KEN", "114", "56", 2000, 2024)
    assert len(df) == 1 and df.iloc[0]["value"] == 4_000_000
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("x.csv", "a,b\n1,2\n")
    with pytest.raises(ProviderSchemaError):
        parse_bulk_zip(bad, "KEN", "114", "56", 2000, 2024)
    _ = io


def test_faostat_reference_mapping():
    assert area_code_for_iso3("KEN") == "114"
    with pytest.raises(ValueError):
        area_code_for_iso3("XDM")
    assert fao_item_for_commodity("Maize flour (white)") == ("56", "Maize (corn)")
    assert fao_item_for_commodity("Fuel (diesel)") is None
