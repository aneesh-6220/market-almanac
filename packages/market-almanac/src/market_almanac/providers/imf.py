"""Provider D: IMF Data API (SDMX 2.1).

Verified live against ``https://api.imf.org/external/sdmx/2.1`` (2026-11):

* Dataflow discovery: ``GET /dataflow`` (SDMX-ML structure message).
* Data: ``GET /data/{agency},{flow}/{key}?startPeriod=YYYY-MM`` returns
  StructureSpecificData XML where each ``<Series>`` carries dimension attributes and each
  ``<Obs TIME_PERIOD="2025-M06" OBS_VALUE="...">``. Observations without ``OBS_VALUE`` are
  missing (not zero).
* Dataset-level ``PUBLICATION_DATE``/``UPDATE_DATE`` attributes are recorded. IMF also
  publishes monthly *vintage* dataflows (e.g. ``CPI_2026_MAY_VINTAGE``) which allow
  point-in-time reconstruction; the current-vintage adapter records the dataset publication
  date and applies a conservative release lag instead.

Verified series (small, deliberate set — no automatic substitution of other measures):

* ``IMF.STA,CPI`` key ``{ISO3}.CPI._T.IX.M`` – headline CPI, all items, index, monthly.
* ``IMF.STA,CPI`` key ``{ISO3}.CPI.CP01.IX.M`` – CPI food & non-alcoholic beverages, index.
* ``IMF.STA,ER``  key ``{ISO3}.XDC_USD.PA_RT.M`` – national currency per USD, period average.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import pandas as pd

from market_almanac.data.schema import MACRO, coerce
from market_almanac.http import HttpClient, ProviderHTTPError
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

BASE_URL = "https://api.imf.org/external/sdmx/2.1"


@dataclass(frozen=True)
class ImfSeries:
    code: str  # Market Almanac indicator code
    agency: str
    flow: str
    key_template: str  # {iso3} placeholder
    name: str
    unit: str
    release_lag_months: int  # conservative availability lag used for modeling


SERIES: tuple[ImfSeries, ...] = (
    ImfSeries("IMF.CPI.ALL", "IMF.STA", "CPI", "{iso3}.CPI._T.IX.M", "Consumer price index, all items", "index", 2),
    ImfSeries(
        "IMF.CPI.FOOD",
        "IMF.STA",
        "CPI",
        "{iso3}.CPI.CP01.IX.M",
        "Consumer price index, food and non-alcoholic beverages",
        "index",
        2,
    ),
    ImfSeries(
        "IMF.FX.USD",
        "IMF.STA",
        "ER",
        "{iso3}.XDC_USD.PA_RT.M",
        "Exchange rate, national currency per US dollar, period average",
        "national currency per USD",
        1,
    ),
)
SERIES_BY_CODE = {s.code: s for s in SERIES}

_PERIOD_RE = re.compile(r"^(\d{4})-?M(\d{2})$")


def parse_sdmx_period(p: str) -> pd.Timestamp:
    m = _PERIOD_RE.match(p)
    if m:
        return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
    if re.match(r"^\d{4}-\d{2}$", p):
        return pd.Timestamp(p + "-01")
    if re.match(r"^\d{4}$", p):
        return pd.Timestamp(year=int(p), month=1, day=1)
    raise ProviderSchemaError(f"imf: unsupported TIME_PERIOD format {p!r}")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_structure_specific(xml_text: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse an SDMX 2.1 StructureSpecificData message.

    Returns (series list with attrs + observations, dataset-level attributes).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderSchemaError(f"imf: malformed SDMX XML ({exc})") from exc
    if _local(root.tag) == "Error":
        raise DatasetNotAvailable("imf: SDMX error message returned")
    datasets = [el for el in root.iter() if _local(el.tag) == "DataSet"]
    if not datasets:
        raise ProviderSchemaError("imf: no DataSet element in response")
    ds_attrs = {k: v for k, v in datasets[0].attrib.items() if "}" not in k}
    out = []
    for s in datasets[0]:
        if _local(s.tag) != "Series":
            continue
        obs = []
        for o in s:
            if _local(o.tag) != "Obs":
                continue
            tp = o.attrib.get("TIME_PERIOD")
            if tp is None:
                raise ProviderSchemaError("imf: Obs without TIME_PERIOD")
            v = o.attrib.get("OBS_VALUE")
            obs.append(
                {
                    "period": parse_sdmx_period(tp),
                    "value": float(v) if v not in (None, "", "NaN") else None,
                    "attrs": {k: val for k, val in o.attrib.items() if k not in ("TIME_PERIOD", "OBS_VALUE")},
                }
            )
        out.append({"attrs": dict(s.attrib), "obs": obs})
    return out, ds_attrs


def parse_dataflows(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    flows = []
    for el in root.iter():
        if _local(el.tag) == "Dataflow":
            name = next((c.text or "" for c in el if _local(c.tag) == "Name"), "")
            flows.append(
                {
                    "agency": el.attrib.get("agencyID", ""),
                    "id": el.attrib.get("id", ""),
                    "version": el.attrib.get("version", ""),
                    "name": name,
                }
            )
    return flows


class ImfProvider(Provider):
    info = ProviderInfo(
        id="imf",
        name="IMF Data (SDMX 2.1)",
        description="International Monetary Fund statistics: CPI and exchange rates via the SDMX 2.1 REST API.",
        homepage="https://data.imf.org/",
        docs_url="https://data.imf.org/en/Resource-Pages/IMF-API",
        license="IMF Terms of Use (data.imf.org); attribution required; review terms before redistribution.",
        attribution="Source: International Monetary Fund, IMF Data (CPI, ER datasets).",
        auth=AuthKind.NONE,
        auth_env_vars=(),
        datasets=(
            DatasetSpec(
                "macro_monthly",
                "Headline CPI, food CPI, USD exchange rate",
                "monthly",
                "country",
                tuple(s.code for s in SERIES),
                "macro",
            ),
            DatasetSpec("dataflows", "Dataflow discovery", "static", "n/a", ("id",), "reference"),
        ),
        capabilities=("dataflow_discovery", "sdmx21_xml", "series_metadata", "publication_date", "vintage_flows"),
        caveats=(
            "Values are the current vintage; earlier releases may have differed (revisions).",
            "Some country series end early or are discontinued; they are reported, not substituted.",
        ),
    )

    def __init__(self, http: HttpClient) -> None:
        super().__init__(http)

    def is_configured(self) -> bool:
        return True

    async def _probe(self) -> str:
        text = await self.http.get_text(
            f"{BASE_URL}/data/IMF.STA,CPI/USA.CPI._T.IX.M",
            params={"startPeriod": "2024-01", "endPeriod": "2024-02"},
            use_cache=False,
        )
        series, _ = parse_structure_specific(text)
        if not series:
            raise ProviderSchemaError("probe returned no series")
        return "CPI dataflow responded"

    async def discover_dataflows(self) -> list[dict[str, str]]:
        return parse_dataflows(await self.http.get_text(f"{BASE_URL}/dataflow"))

    async def fetch(self, dataset: str, **params: Any) -> FetchResult:
        self.dataset_spec(dataset)
        before = self.http.request_count
        if dataset == "dataflows":
            flows = await self.discover_dataflows()
            return FetchResult(
                self.id,
                dataset,
                pd.DataFrame(flows),
                utcnow(),
                {},
                [f"{BASE_URL}/dataflow"],
                raw_record_count=len(flows),
                requests_made=self.http.request_count - before,
            )
        iso3 = str(params["country_iso3"]).upper()
        codes = params.get("indicators") or [s.code for s in SERIES]
        start = params.get("start_period", "2000-01")
        frames, warnings, raw_n, urls = [], [], 0, []
        status: dict[str, str] = {}
        for code in codes:
            spec = SERIES_BY_CODE[code]
            url = f"{BASE_URL}/data/{spec.agency},{spec.flow}/{spec.key_template.format(iso3=iso3)}"
            urls.append(url)
            try:
                text = await self.http.get_text(url, params={"startPeriod": start})
            except ProviderHTTPError as exc:
                if exc.status_code in (404, 204):
                    status[code] = "unavailable"
                    warnings.append(f"{code}: no data for {iso3} (HTTP {exc.status_code}); not substituted")
                    continue
                raise
            if not text.strip():
                status[code] = "unavailable"
                warnings.append(f"{code}: empty response for {iso3}; not substituted")
                continue
            series, ds_attrs = parse_structure_specific(text)
            if not series:
                status[code] = "unavailable"
                warnings.append(f"{code}: no series for {iso3}; not substituted")
                continue
            frame = series_to_frame(series, ds_attrs, spec, iso3)
            raw_n += sum(len(s["obs"]) for s in series)
            status[code] = "ok" if len(frame) else "no_observations"
            frames.append(frame)
        frame = coerce(pd.concat(frames, ignore_index=True), MACRO) if frames else coerce(pd.DataFrame(), MACRO)
        return FetchResult(
            self.id,
            dataset,
            frame,
            utcnow(),
            dict(params),
            urls,
            warnings,
            raw_n,
            self.http.request_count - before,
            extra={"series_status": status},
        )


def series_to_frame(series: list[dict[str, Any]], ds_attrs: dict[str, str], spec: ImfSeries, iso3: str) -> pd.DataFrame:
    pub = ds_attrs.get("PUBLICATION_DATE")
    recs = []
    for s in series:
        a = s["attrs"]
        ref = ",".join(f"{k}={v}" for k, v in a.items() if k in ("COMMON_REFERENCE_PERIOD", "SCALE"))
        for o in s["obs"]:
            if o["value"] is None:
                continue
            recs.append(
                {
                    "provider": "imf",
                    "country_iso3": iso3,
                    "indicator_code": spec.code,
                    "indicator_name": spec.name,
                    "frequency": "M",
                    "period": o["period"],
                    "value": o["value"],
                    "unit": spec.unit + (f" ({ref})" if ref else ""),
                    "source_ref": f"imf:{spec.agency},{spec.flow}/{spec.key_template.format(iso3=iso3)}",
                    # Dataset-level publication date of the *current vintage*; not the first release date.
                    "published_at": pd.NaT,
                    "retrieved_at": utcnow(),
                    "quality_flags": f"vintage_published={pub}" if pub else "",
                }
            )
    return pd.DataFrame(recs)
