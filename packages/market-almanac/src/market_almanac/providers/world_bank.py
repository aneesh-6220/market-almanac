"""Provider C: World Bank Indicators API (V2).

Docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392

* ``GET https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?format=json&per_page=N&date=Y1:Y2``
  returns ``[page_meta, rows]``; errors are returned as ``[{"message": [...]}]`` with HTTP 200.
* ``GET https://api.worldbank.org/v2/country/{iso3}?format=json`` returns country metadata.

All initial indicators are ANNUAL. They are exposed as context and are never interpolated
into monthly values. If used as model features, ``market_almanac.data.alignment`` applies an
explicit as-of availability rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from market_almanac.data.schema import COUNTRIES, MACRO, coerce
from market_almanac.http import HttpClient
from market_almanac.providers.base import (
    AuthKind,
    DatasetNotAvailable,
    DatasetSpec,
    FetchResult,
    Provider,
    ProviderInfo,
    ProviderSchemaError,
    utcnow,
)

BASE_URL = "https://api.worldbank.org/v2"
PER_PAGE = 1000
MAX_PAGES = 20


@dataclass(frozen=True)
class WbIndicator:
    code: str
    name: str
    unit: str
    justification: str


INDICATORS: tuple[WbIndicator, ...] = (
    WbIndicator("SP.POP.TOTL", "Population, total", "people", "Demand-side scale; context only."),
    WbIndicator("SP.POP.GROW", "Population growth (annual %)", "% per year", "Demand growth context."),
    WbIndicator(
        "NY.GDP.PCAP.KD",
        "GDP per capita (constant 2015 US$)",
        "constant 2015 USD",
        "Income level shapes food budget shares and price sensitivity.",
    ),
    WbIndicator("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)", "% per year", "Macroeconomic cycle context."),
    WbIndicator(
        "FP.CPI.TOTL.ZG",
        "Inflation, consumer prices (annual %)",
        "% per year",
        "General inflation backdrop for nominal food prices (annual; monthly CPI comes from IMF).",
    ),
    WbIndicator("AG.PRD.FOOD.XD", "Food production index (2014-2016 = 100)", "index", "National food supply context."),
    WbIndicator(
        "NV.AGR.TOTL.ZS",
        "Agriculture, forestry, and fishing, value added (% of GDP)",
        "% of GDP",
        "Economic exposure to agricultural shocks.",
    ),
)
INDICATOR_BY_CODE = {i.code: i for i in INDICATORS}


class WorldBankProvider(Provider):
    info = ProviderInfo(
        id="world_bank",
        name="World Bank Indicators (WDI)",
        description="World Development Indicators via the World Bank Indicators API V2.",
        homepage="https://data.worldbank.org/",
        docs_url="https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
        license=(
            "Creative Commons Attribution 4.0 (CC BY 4.0) for most WDI indicators; check each indicator's source note."
        ),
        attribution="Source: World Bank, World Development Indicators.",
        auth=AuthKind.NONE,
        auth_env_vars=(),
        datasets=(
            DatasetSpec(
                "indicators",
                "Selected annual development indicators",
                "annual",
                "country",
                tuple(i.code for i in INDICATORS),
                "macro",
            ),
            DatasetSpec(
                "countries",
                "Country metadata (region, income level)",
                "static",
                "country",
                ("region", "incomeLevel"),
                "countries",
            ),
        ),
        capabilities=("country_metadata", "indicator_retrieval", "pagination"),
        caveats=("Indicators are annual; Market Almanac does not interpolate them to months.",),
    )

    def __init__(self, http: HttpClient) -> None:
        super().__init__(http)

    def is_configured(self) -> bool:
        return True

    async def _probe(self) -> str:
        payload = await self.http.get_json(f"{BASE_URL}/country/KEN", params={"format": "json"}, use_cache=False)
        _check_error(payload)
        return "country endpoint responded"

    async def fetch(self, dataset: str, **params: Any) -> FetchResult:
        self.dataset_spec(dataset)
        before = self.http.request_count
        iso3 = str(params["country_iso3"]).upper()
        warnings: list[str] = []
        if dataset == "countries":
            payload = await self.http.get_json(f"{BASE_URL}/country/{iso3}", params={"format": "json"})
            frame = parse_country(payload)
            raw_n = len(frame)
        else:
            codes = params.get("indicators") or [i.code for i in INDICATORS]
            start_year, end_year = int(params.get("start_year", 2000)), int(params.get("end_year", utcnow().year))
            frames = []
            raw_n = 0
            for code in codes:
                try:
                    rows, last_updated = await self._indicator(iso3, code, start_year, end_year)
                except DatasetNotAvailable as exc:
                    warnings.append(str(exc))
                    continue
                raw_n += len(rows)
                frames.append(parse_indicator_rows(rows, code, last_updated))
            frame = coerce(pd.concat(frames, ignore_index=True), MACRO) if frames else coerce(pd.DataFrame(), MACRO)
        return FetchResult(
            provider_id=self.id,
            dataset=dataset,
            frame=frame,
            fetched_at=utcnow(),
            params=dict(params),
            source_urls=[BASE_URL],
            warnings=warnings,
            raw_record_count=raw_n,
            requests_made=self.http.request_count - before,
        )

    async def _indicator(self, iso3: str, code: str, y0: int, y1: int) -> tuple[list[dict[str, Any]], str | None]:
        rows: list[dict[str, Any]] = []
        last_updated = None
        for page in range(1, MAX_PAGES + 1):
            payload = await self.http.get_json(
                f"{BASE_URL}/country/{iso3}/indicator/{code}",
                params={"format": "json", "per_page": PER_PAGE, "page": page, "date": f"{y0}:{y1}"},
            )
            _check_error(payload, code)
            meta, data = payload[0], payload[1] or []
            last_updated = meta.get("lastupdated")
            rows.extend(data)
            if page >= int(meta.get("pages", 1)):
                break
        return rows, last_updated


def _check_error(payload: Any, code: str | None = None) -> None:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "message" in payload[0]:
        msgs = "; ".join(m.get("value", m.get("key", "")) for m in payload[0]["message"])
        raise DatasetNotAvailable(f"world_bank: {code or 'request'} unavailable: {msgs}")
    if not isinstance(payload, list) or len(payload) < 2:
        raise ProviderSchemaError("world_bank: expected [meta, rows] array")


def parse_indicator_rows(rows: list[dict[str, Any]], code: str, last_updated: str | None) -> pd.DataFrame:
    ind = INDICATOR_BY_CODE.get(code)
    recs = []
    for r in rows:
        try:
            year = int(r["date"])
            iso3 = r["countryiso3code"]
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderSchemaError(f"world_bank: malformed row for {code}: {exc}") from exc
        if r.get("value") is None:
            continue  # missing observation, not zero
        recs.append(
            {
                "provider": "world_bank",
                "country_iso3": iso3,
                "indicator_code": code,
                "indicator_name": (r.get("indicator") or {}).get("value") or (ind.name if ind else code),
                "frequency": "A",
                "period": pd.Timestamp(year=year, month=1, day=1),
                "value": float(r["value"]),
                "unit": ind.unit if ind else (r.get("unit") or ""),
                "source_ref": f"wb:{code}" + (f"@lastupdated={last_updated}" if last_updated else ""),
                "published_at": pd.NaT,  # per-value release dates are not provided
                "retrieved_at": utcnow(),
                "quality_flags": r.get("obs_status") or "",
            }
        )
    return pd.DataFrame(recs)


def parse_country(payload: Any) -> pd.DataFrame:
    _check_error(payload)
    rows = payload[1] or []
    recs = [
        {
            "iso3": r["id"],
            "name": r["name"],
            "region": (r.get("region") or {}).get("value"),
            "income_level": (r.get("incomeLevel") or {}).get("value"),
            "provider": "world_bank",
            "retrieved_at": utcnow(),
        }
        for r in rows
    ]
    return coerce(pd.DataFrame(recs), COUNTRIES)
