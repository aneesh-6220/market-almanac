"""Provider E: FAOSTAT.

Two clearly distinguished access paths:

1. **Authenticated API** (``https://faostatservices.fao.org/api/v1``), documented at
   https://www.fao.org/faostat/en/docs/redoc-static.html. All endpoints require
   ``Authorization: Bearer <AccessToken>``. Tokens are AWS Cognito access tokens with a
   short lifetime (~1 h). Configure either ``FAOSTAT_ACCESS_TOKEN`` (used until expiry) or
   ``FAOSTAT_USERNAME``/``FAOSTAT_PASSWORD`` (``POST /auth/login``, form-encoded) so the
   adapter can obtain fresh tokens.

   Data: ``GET /en/data/QCL?area=&item=&element=&year=&output_type=objects``.
   NOTE (verified live): the *query* element codes for QCL are 2312 (area harvested),
   2413 (yield), 2510 (production), while *returned* rows carry 5312, 5412, 5510.

2. **Public bulk download** (no credentials): the normalized QCL archive at
   ``https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip``
   (URL as listed by the authenticated ``/bulkdownloads/QCL/`` endpoint). Areas are keyed by
   FAO area code and M49; Market Almanac maps ISO3 via a reference table generated from the
   FAOSTAT area definitions.

FAOSTAT data are ANNUAL and NATIONAL. They do not identify the farms or regions that
supply any particular market.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import time
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.config import Settings
from market_almanac.data.schema import AGRICULTURE, coerce
from market_almanac.http import HttpClient, ProviderHTTPError
from market_almanac.providers.base import (
    AuthKind,
    DatasetSpec,
    FetchResult,
    Provider,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderSchemaError,
    utcnow,
)

API_URL = "https://faostatservices.fao.org/api/v1"
BULK_QCL_URL = "https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip"

# Query code -> (returned code, name, unit)
QCL_ELEMENTS = {
    "2312": ("5312", "Area harvested", "ha"),
    "2413": ("5412", "Yield", "kg/ha"),
    "2510": ("5510", "Production", "t"),
}
RETURNED_ELEMENT_CODES = {v[0] for v in QCL_ELEMENTS.values()}

# Explicit, documented classification mapping from WFP commodity name keywords to the FAOSTAT
# primary crop item. This links a *product type* to national production statistics of the
# related crop. It is NOT a supply-chain or origin mapping.
COMMODITY_TO_FAO_ITEM: dict[str, tuple[str, str]] = {
    # Checked in order: more specific keywords first.
    "niebe": ("195", "Cow peas, dry"),
    "cowpea": ("195", "Cow peas, dry"),
    "groundnut": ("242", "Groundnuts, excluding shelled"),
    "maize": ("56", "Maize (corn)"),
    "rice": ("27", "Rice"),
    "sorghum": ("83", "Sorghum"),
    "wheat": ("15", "Wheat"),
    "millet": ("79", "Millet"),
    "beans": ("176", "Beans, dry"),
    "potatoes": ("116", "Potatoes"),
    "cassava": ("125", "Cassava, fresh"),
    "teff": ("839", "Cereals n.e.c."),
}


def fao_item_for_commodity(commodity_name: str) -> tuple[str, str] | None:
    name = commodity_name.lower()
    for kw, item in COMMODITY_TO_FAO_ITEM.items():
        if kw in name:
            return item
    return None


def jwt_expiry(token: str) -> float | None:
    """Return the ``exp`` claim (epoch seconds) of a JWT without verifying it."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return float(json.loads(base64.urlsafe_b64decode(part))["exp"])
    except (IndexError, KeyError, ValueError, json.JSONDecodeError):
        return None


@dataclass
class _Token:
    value: str
    expires_at: float | None


def load_iso3_map() -> pd.DataFrame:
    """ISO3 <-> FAO area code <-> M49 reference table shipped with the package."""
    with resources.files("market_almanac.providers").joinpath("faostat_areas.csv").open() as fh:
        return pd.read_csv(fh, dtype=str)


class FaostatProvider(Provider):
    info = ProviderInfo(
        id="faostat",
        name="FAOSTAT",
        description="FAO statistics on crop production, yield and harvested area (domain QCL).",
        homepage="https://www.fao.org/faostat/en/",
        docs_url="https://www.fao.org/faostat/en/docs/redoc-static.html",
        license="FAO data are licensed CC BY 4.0 (FAO Statistical Database Terms of Use); attribution required.",
        attribution="Source: FAO. FAOSTAT, Crops and livestock products (QCL).",
        auth=AuthKind.BEARER_TOKEN,
        auth_env_vars=("FAOSTAT_ACCESS_TOKEN", "FAOSTAT_USERNAME", "FAOSTAT_PASSWORD"),
        datasets=(
            DatasetSpec(
                "crop_production",
                "Annual production, yield and harvested area for a crop",
                "annual",
                "country",
                ("5510", "5412", "5312"),
                "agriculture",
            ),
            DatasetSpec(
                "crop_production_bulk",
                "Same data from the public bulk archive (no credentials)",
                "annual",
                "country",
                ("5510", "5412", "5312"),
                "agriculture",
            ),
        ),
        capabilities=("authenticated_api", "token_refresh_via_login", "public_bulk_download", "code_preservation"),
        caveats=(
            "Annual national statistics; not a mapping of the farms supplying any market.",
            "Latest year typically released ~12 months after the end of the reference year.",
        ),
    )

    def __init__(self, http: HttpClient, settings: Settings) -> None:
        super().__init__(http)
        self._settings = settings
        tok = settings.faostat_access_token.get_secret_value().strip() if settings.faostat_access_token else ""
        self._token: _Token | None = _Token(tok, jwt_expiry(tok)) if tok else None

    def has_login(self) -> bool:
        return bool(self._settings.faostat_username and self._settings.faostat_password)

    def token_valid(self, now: float | None = None) -> bool:
        if not self._token:
            return False
        exp = self._token.expires_at
        return exp is None or exp - 60 > (now or time.time())

    def is_configured(self) -> bool:
        return self.token_valid() or self.has_login()

    def credential_state(self) -> str:
        if self.token_valid():
            return "token_valid"
        if self.has_login():
            return "login_configured"
        if self._token:
            return "token_expired"
        return "missing"

    async def _bearer(self) -> dict[str, str]:
        if self.token_valid():
            assert self._token is not None
            return {"Authorization": f"Bearer {self._token.value}"}
        if self.has_login():
            assert self._settings.faostat_password is not None
            resp = await self.http.request(
                "POST",
                f"{API_URL}/auth/login",
                data={
                    "username": self._settings.faostat_username,
                    "password": self._settings.faostat_password.get_secret_value(),
                },
                use_cache=False,
            )
            try:
                tok = json.loads(resp.text)["AuthenticationResult"]["AccessToken"]
            except (KeyError, json.JSONDecodeError) as exc:
                raise ProviderSchemaError("faostat: login response missing AccessToken") from exc
            self._token = _Token(tok, jwt_expiry(tok))
            return {"Authorization": f"Bearer {tok}"}
        state = "expired" if self._token else "not set"
        raise ProviderNotConfigured(
            f"FAOSTAT access token {state}; set FAOSTAT_USERNAME/FAOSTAT_PASSWORD or a fresh FAOSTAT_ACCESS_TOKEN, "
            "or use the public bulk dataset 'crop_production_bulk'."
        )

    async def _probe(self) -> str:
        payload = await self.http.get_json(
            f"{API_URL}/en/definitions/types", secret_headers=await self._bearer(), use_cache=False
        )
        if "data" not in payload:
            raise ProviderSchemaError("definitions/types missing 'data'")
        return "definitions endpoint responded (authenticated)"

    async def fetch(self, dataset: str, **params: Any) -> FetchResult:
        self.dataset_spec(dataset)
        before = self.http.request_count
        iso3 = str(params["country_iso3"]).upper()
        item_code = str(params["item_code"])
        y0, y1 = int(params.get("start_year", 2000)), int(params.get("end_year", utcnow().year))
        area = area_code_for_iso3(iso3)
        if dataset == "crop_production":
            payload = await self.http.get_json(
                f"{API_URL}/en/data/QCL",
                params={
                    "area": area,
                    "item": item_code,
                    "element": ",".join(QCL_ELEMENTS),
                    "year": ",".join(str(y) for y in range(y0, y1 + 1)),
                    "output_type": "objects",
                    "show_codes": "true",
                    "show_unit": "true",
                    "show_flags": "true",
                },
                secret_headers=await self._bearer(),
            )
            rows = payload.get("data") if isinstance(payload, dict) else None
            if rows is None:
                raise ProviderSchemaError("faostat: data response missing 'data'")
            frame = parse_api_rows(rows, iso3, source_ref=f"faostat:api:QCL:{area}:{item_code}")
            urls = [f"{API_URL}/en/data/QCL"]
        else:
            frame = await self._bulk(iso3, area, item_code, y0, y1)
            rows = frame
            urls = [BULK_QCL_URL]
        return FetchResult(
            self.id,
            dataset,
            frame,
            utcnow(),
            dict(params),
            urls,
            [] if len(frame) else ["no observations returned"],
            len(rows),
            self.http.request_count - before,
        )

    async def _bulk(self, iso3: str, area: str, item_code: str, y0: int, y1: int) -> pd.DataFrame:
        cache_dir = self.http.config.cache_dir or Path("./data/cache")
        zpath = cache_dir / "faostat" / "QCL_normalized.zip"
        if not zpath.exists() or time.time() - zpath.stat().st_mtime > 30 * 86400:
            zpath.parent.mkdir(parents=True, exist_ok=True)
            resp = await self._download(BULK_QCL_URL)
            zpath.write_bytes(resp)
        return parse_bulk_zip(zpath, iso3, area, item_code, y0, y1)

    async def _download(self, url: str) -> bytes:
        import httpx

        self.http._check_host(url)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True, transport=self.http._transport) as c:
            r = await c.get(url)
        if r.status_code != 200:
            raise ProviderHTTPError(f"bulks-faostat.fao.org returned HTTP {r.status_code}", r.status_code)
        return r.content


def area_code_for_iso3(iso3: str) -> str:
    m = load_iso3_map()
    hit = m[m["iso3"] == iso3]
    if hit.empty:
        raise ValueError(f"No FAOSTAT area code known for ISO3 {iso3}")
    return str(hit.iloc[0]["fao_area_code"])


def parse_api_rows(rows: list[dict[str, Any]], iso3: str, source_ref: str) -> pd.DataFrame:
    recs = []
    for r in rows:
        try:
            ec = str(r["Element Code"])
            recs.append(
                {
                    "provider": "faostat",
                    "country_iso3": iso3,
                    "fao_area_code": str(r["Area Code"]),
                    "domain_code": r.get("Domain Code", "QCL"),
                    "item_code": str(r["Item Code"]),
                    "item_name": r["Item"],
                    "element_code": ec,
                    "element_name": r["Element"],
                    "unit": r["Unit"],
                    "year": int(r["Year"]),
                    "value": float(r["Value"]) if r.get("Value") not in (None, "") else None,
                    "flag": r.get("Flag", ""),
                    "flag_description": r.get("Flag Description", ""),
                    "source_ref": source_ref,
                    "published_at": pd.NaT,
                    "retrieved_at": utcnow(),
                }
            )
        except (KeyError, ValueError) as exc:
            raise ProviderSchemaError(f"faostat: malformed data row ({exc})") from exc
    df = pd.DataFrame(recs)
    if len(df):
        df = df[df["element_code"].isin(RETURNED_ELEMENT_CODES) & df["value"].notna()]
    return coerce(df, AGRICULTURE)


def parse_bulk_zip(zpath: Path, iso3: str, area: str, item_code: str, y0: int, y1: int) -> pd.DataFrame:
    with zipfile.ZipFile(zpath) as zf:
        name = next((n for n in zf.namelist() if n.endswith("(Normalized).csv")), None)
        if name is None:
            raise ProviderSchemaError("faostat bulk: normalized CSV not found in archive")
        recs = []
        with zf.open(name) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"))
            needed = {"Area Code", "Item Code", "Element Code", "Element", "Item", "Year", "Unit", "Value", "Flag"}
            if reader.fieldnames is None or not needed.issubset(reader.fieldnames):
                raise ProviderSchemaError(f"faostat bulk: unexpected columns {reader.fieldnames}")
            for r in reader:
                if r["Area Code"] != area or r["Item Code"] != item_code:
                    continue
                if r["Element Code"] not in RETURNED_ELEMENT_CODES:
                    continue
                yr = int(r["Year"])
                if not (y0 <= yr <= y1) or r["Value"] in ("", None):
                    continue
                recs.append(
                    {
                        "provider": "faostat",
                        "country_iso3": iso3,
                        "fao_area_code": area,
                        "domain_code": "QCL",
                        "item_code": item_code,
                        "item_name": r["Item"],
                        "element_code": r["Element Code"],
                        "element_name": r["Element"],
                        "unit": r["Unit"],
                        "year": yr,
                        "value": float(r["Value"]),
                        "flag": r.get("Flag", ""),
                        "flag_description": "",
                        "source_ref": "faostat:bulk:QCL",
                        "published_at": pd.NaT,
                        "retrieved_at": utcnow(),
                    }
                )
    return coerce(pd.DataFrame(recs), AGRICULTURE)
