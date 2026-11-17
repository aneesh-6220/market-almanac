"""Provider A: WFP food prices via HDX HAPI (v2).

Endpoints (verified against https://hapi.humdata.org/openapi.json, HAPI 0.9.x):

* ``/api/v2/food-security-nutrition-poverty/food-prices-market-monitor``
* ``/api/v2/metadata/wfp-market``, ``/api/v2/metadata/wfp-commodity``,
  ``/api/v2/metadata/currency``, ``/api/v2/metadata/location``

Every request needs an ``app_identifier`` (base64 of "app_name:email"). We send it as the
``X-HDX-HAPI-APP-IDENTIFIER`` header so it never appears in URLs, logs or cache keys.

HAPI converts WFP's original date (the 15th of a month) into a reference period that runs
from the 15th to the 14th of the next month. Market Almanac labels the observation with the
calendar month of ``reference_period_start`` (i.e. WFP's original month).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from market_almanac.config import Settings
from market_almanac.data.identity import series_id
from market_almanac.data.schema import PRICES, coerce
from market_almanac.http import HttpClient
from market_almanac.providers.base import (
    AuthKind,
    DatasetSpec,
    FetchResult,
    Provider,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderSchemaError,
    require_fields,
    utcnow,
)

BASE_URL = "https://hapi.humdata.org/api/v2"
FOOD_PRICE_PATH = "/food-security-nutrition-poverty/food-prices-market-monitor"
PAGE_LIMIT = 10_000  # HAPI hard maximum per request
MAX_PAGES = 200  # bounded retrieval: at most 2M rows per call

FOOD_PRICE_FIELDS = (
    "location_code",
    "location_name",
    "admin1_name",
    "admin2_name",
    "resource_hdx_id",
    "market_code",
    "market_name",
    "commodity_code",
    "commodity_name",
    "commodity_category",
    "currency_code",
    "unit",
    "price_flag",
    "price_type",
    "price",
    "lat",
    "lon",
    "reference_period_start",
    "reference_period_end",
)
PRICE_TYPES = ("Farm Gate", "Producer", "Retail", "Wholesale")
PRICE_FLAGS = ("actual", "aggregate", "actual,aggregate")


class HdxHapiProvider(Provider):
    info = ProviderInfo(
        id="hdx_hapi",
        name="WFP Food Prices (HDX HAPI)",
        description=(
            "World Food Programme market price database (monthly, ~98 countries, ~3000 markets) "
            "served through OCHA's Humanitarian API (HDX HAPI)."
        ),
        homepage="https://data.humdata.org/",
        docs_url="https://hdx-hapi.readthedocs.io/en/latest/",
        license=(
            "Governed by the HDX HAPI Terms of Use and the licence of each underlying HDX dataset "
            "(the WFP food price datasets on HDX are published under a Creative Commons licence; "
            "verify the licence on the dataset page before redistribution)."
        ),
        attribution="Source: World Food Programme (WFP) via HDX HAPI, OCHA Centre for Humanitarian Data.",
        auth=AuthKind.APP_IDENTIFIER,
        auth_env_vars=("HDX_HAPI_APP_IDENTIFIER",),
        datasets=(
            DatasetSpec(
                "food_prices", "Monthly market-commodity prices", "monthly", "market point", ("price",), "prices"
            ),
            DatasetSpec(
                "markets", "WFP market metadata with coordinates", "static", "market point", ("lat", "lon"), "reference"
            ),
            DatasetSpec(
                "commodities", "WFP commodity list and categories", "static", "n/a", ("category",), "reference"
            ),
            DatasetSpec("currencies", "ISO-4217 currencies", "static", "n/a", ("code",), "reference"),
            DatasetSpec("locations", "Countries covered by HAPI", "static", "country", ("code",), "reference"),
        ),
        capabilities=(
            "discover_countries",
            "discover_markets",
            "discover_commodities",
            "price_history",
            "filter_country_market_commodity_pricetype_date",
            "pagination",
            "incremental_refresh",
        ),
        caveats=(
            "Commodity names are not interchangeable: units, qualities, price types, and currencies differ.",
            "HAPI coverage of WFP prices begins in 2017 for most countries.",
            "Original publication dates of individual prices are not provided by HAPI.",
        ),
    )

    def __init__(self, http: HttpClient, settings: Settings) -> None:
        super().__init__(http)
        self._app_id = settings.hdx_hapi_app_identifier

    def is_configured(self) -> bool:
        return self._app_id is not None and bool(self._app_id.get_secret_value().strip())

    def _secret_headers(self) -> dict[str, str]:
        if not self.is_configured():
            raise ProviderNotConfigured("HDX_HAPI_APP_IDENTIFIER is not set")
        assert self._app_id is not None
        return {"X-HDX-HAPI-APP-IDENTIFIER": self._app_id.get_secret_value().strip()}

    async def _get(self, path: str, params: dict[str, Any], use_cache: bool = True) -> list[dict[str, Any]]:
        payload = await self.http.get_json(
            BASE_URL + path,
            params={**params, "output_format": "json"},
            secret_headers=self._secret_headers(),
            use_cache=use_cache,
        )
        if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload["data"], list):
            raise ProviderSchemaError("hdx_hapi: response missing 'data' list")
        return payload["data"]

    async def _paginate(self, path: str, params: dict[str, Any], use_cache: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            batch = await self._get(path, {**params, "limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT}, use_cache)
            rows.extend(batch)
            if len(batch) < PAGE_LIMIT:
                return rows
        raise ProviderSchemaError(f"hdx_hapi: exceeded {MAX_PAGES} pages; narrow the query")

    async def _probe(self) -> str:
        rows = await self._get("/metadata/location", {"limit": 1, "code": "KEN"}, use_cache=False)
        if not rows:
            raise ProviderSchemaError("location metadata returned no rows")
        require_fields(rows[0], ("code", "name"), "hdx_hapi")
        return "metadata/location responded"

    async def fetch(self, dataset: str, **params: Any) -> FetchResult:
        self.dataset_spec(dataset)
        before = self.http.request_count
        if dataset == "food_prices":
            frame, raw_n, warnings = await self._fetch_prices(**params)
        else:
            path = {
                "markets": "/metadata/wfp-market",
                "commodities": "/metadata/wfp-commodity",
                "currencies": "/metadata/currency",
                "locations": "/metadata/location",
            }[dataset]
            q = {k: v for k, v in params.items() if v is not None}
            raw = await self._paginate(path, q, use_cache=params.get("use_cache", True))
            frame, raw_n, warnings = pd.DataFrame(raw), len(raw), []
        return FetchResult(
            provider_id=self.id,
            dataset=dataset,
            frame=frame,
            fetched_at=utcnow(),
            params={k: v for k, v in params.items()},
            source_urls=[BASE_URL + FOOD_PRICE_PATH],
            warnings=warnings,
            raw_record_count=raw_n,
            requests_made=self.http.request_count - before,
        )

    async def _fetch_prices(
        self,
        country_iso3: str,
        commodity_code: str | None = None,
        market_code: str | None = None,
        price_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        use_cache: bool = True,
    ) -> tuple[pd.DataFrame, int, list[str]]:
        if not country_iso3 or len(country_iso3) != 3 or not country_iso3.isalpha():
            raise ValueError("country_iso3 must be a 3-letter ISO code")
        if price_type is not None and price_type not in PRICE_TYPES:
            raise ValueError(f"price_type must be one of {PRICE_TYPES}")
        q: dict[str, Any] = {"location_code": country_iso3.upper()}
        for k, v in (
            ("commodity_code", commodity_code),
            ("market_code", market_code),
            ("price_type", price_type),
            ("start_date", start_date),
            ("end_date", end_date),
        ):
            if v is not None:
                q[k] = v
        raw = await self._paginate(FOOD_PRICE_PATH, q, use_cache=use_cache)
        retrieved = utcnow()
        return normalize_food_prices(raw, retrieved)


def normalize_food_prices(raw: list[dict[str, Any]], retrieved_at: Any) -> tuple[pd.DataFrame, int, list[str]]:
    """Normalize HAPI food-price rows to the canonical PRICES schema.

    Exact duplicate rows are collapsed. Conflicting duplicates (same identity and month,
    different price) are kept and flagged ``duplicate_conflict`` so quality control can
    exclude them; they are never averaged silently.
    """
    warnings: list[str] = []
    if not raw:
        from market_almanac.data.schema import empty_frame

        return empty_frame(PRICES), 0, ["no records returned"]
    for r in raw[:5]:
        require_fields(r, FOOD_PRICE_FIELDS, "hdx_hapi")
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "provider": "hdx_hapi",
            "country_iso3": df["location_code"].str.upper(),
            "admin1_name": df["admin1_name"],
            "admin2_name": df["admin2_name"],
            "market_code": df["market_code"].astype(str),
            "market_name": df["market_name"],
            "lat": pd.to_numeric(df["lat"], errors="coerce"),
            "lon": pd.to_numeric(df["lon"], errors="coerce"),
            "commodity_code": df["commodity_code"].astype(str),
            "commodity_name": df["commodity_name"],
            "commodity_category": df["commodity_category"],
            "unit": df["unit"].astype(str).str.strip(),
            "price_type": df["price_type"],
            "price_flag": df["price_flag"],
            "currency": df["currency_code"].astype(str).str.upper(),
            "price": pd.to_numeric(df["price"], errors="coerce"),
            "source_ref": "hdx:" + df["resource_hdx_id"].astype(str),
            "reference_period_start": pd.to_datetime(df["reference_period_start"], errors="coerce"),
            "reference_period_end": pd.to_datetime(df["reference_period_end"], errors="coerce"),
            "published_at": pd.NaT,  # HAPI does not expose original publication dates
            "retrieved_at": retrieved_at,
        }
    )
    out["period"] = out["reference_period_start"].dt.to_period("M").dt.to_timestamp()
    bad_dates = out["period"].isna().sum()
    if bad_dates:
        warnings.append(f"{bad_dates} rows with unparseable reference periods dropped")
        out = out[out["period"].notna()]
    out["series_id"] = [
        series_id(
            provider="hdx_hapi",
            country_iso3=r.country_iso3,
            market_code=r.market_code,
            commodity_code=r.commodity_code,
            unit=r.unit,
            price_type=r.price_type,
            price_flag=r.price_flag,
            currency=r.currency,
        )
        for r in out.itertuples()
    ]
    flags = pd.Series("", index=out.index, dtype="string")
    nonpos = out["price"].isna() | (out["price"] <= 0)
    flags[nonpos] = "invalid_price"
    out["quality_flags"] = flags

    n0 = len(out)
    out = out.drop_duplicates(subset=["series_id", "period", "price"])
    if len(out) < n0:
        warnings.append(f"{n0 - len(out)} exact duplicate rows collapsed")
    conflict = out.duplicated(["series_id", "period"], keep=False)
    if conflict.any():
        out.loc[conflict, "quality_flags"] = (
            out.loc[conflict, "quality_flags"]
            .fillna("")
            .str.cat(["duplicate_conflict"] * int(conflict.sum()), sep=",")
            .str.strip(",")
        )
        warnings.append(f"{int(conflict.sum())} rows have conflicting prices for the same series-month")
    return coerce(out, PRICES), len(raw), warnings
