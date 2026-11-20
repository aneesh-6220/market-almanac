"""IMF consumer prices and exchange rates for the Economic Context Engine (SDMX 2.1 bulk retrieval and validation).

Verified against ``https://api.imf.org/external/sdmx/2.1`` on 2026-11-20. One wildcard request returns a concept for
every country (about 3 MB), so retrieval is four requests, not hundreds; the adapter is not tied to any list of
countries and covers whatever the IMF publishes.

Concepts (the dataflow keys are ``COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY`` for ``CPI`` and
``COUNTRY.INDICATOR.TYPE_OF_TRANSFORMATION.FREQUENCY`` for ``ER``):

========================  ======================  ===================================================
concept                   key                     meaning
========================  ======================  ===================================================
``cpi_headline``          ``.CPI._T.IX.M``        consumer price index, all items, index level
``cpi_food``              ``.CPI.CP01.IX.M``      CPI, food and non-alcoholic beverages (COICOP 01)
``fx_period_avg``         ``.XDC_USD.PA_RT.M``    national currency per US dollar, period average
``fx_end_period``         ``.XDC_USD.EOP_RT.M``   national currency per US dollar, end of period
========================  ======================  ===================================================

Index **levels** are stored, never the IMF's published percentage changes: changes are computed here by a stated
formula (:mod:`market_almanac.context.transforms`), so each can be reproduced from the stored levels. Monthly and
annual observations are never mixed: a ``TIME_PERIOD`` that is not ``YYYY-Mnn`` is rejected.

What validation rejects (each recorded with its reason, none silently dropped or repaired):

* ``future_period``: a reference month after the month of retrieval (observed: Zimbabwe, an exchange-rate value
  labelled 2027-M03 that repeats March 2026);
* ``non_monthly_period``, ``non_positive_level``, ``duplicate_period``, ``non_country_code``.

What is **recorded, not rejected**: observations that the IMF lists without a value (``n_source_empty``; 47% of the
food-CPI observations in the 2026-11-19 vintage, and every observation of Niger's food-CPI series), and reference-period
changes of a CPI series, with the months at which the level is discontinuous (``base_breaks``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.context import transforms as T
from market_almanac.http import HttpClient
from market_almanac.providers.base import ProviderSchemaError
from market_almanac.providers.imf import BASE_URL

_ISO3 = re.compile(r"^[A-Z]{3}$")
_MONTHLY = re.compile(r"^\d{4}-M(0[1-9]|1[0-2])$")
_STRUCT = re.compile(r'<Ref agencyID="([^"]+)" id="([^"]+)" version="([^"]+)"')
DEFAULT_START = "2010-01"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sdmx(text: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse StructureSpecificData into series (attributes plus observations with the raw ``TIME_PERIOD``) and the
    dataset attributes. An observation without ``OBS_VALUE`` has ``value`` None: missing, never zero."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderSchemaError(f"imf: malformed SDMX XML ({exc})") from exc
    if _local(root.tag) == "Error":
        raise ProviderSchemaError("imf: SDMX error message returned")
    datasets = [el for el in root.iter() if _local(el.tag) == "DataSet"]
    if not datasets:
        raise ProviderSchemaError("imf: no DataSet element in response")
    ds = {k: v for k, v in datasets[0].attrib.items() if "}" not in k}
    out: list[dict[str, Any]] = []
    for s in datasets[0]:
        if _local(s.tag) != "Series":
            continue
        obs = []
        for o in s:
            if _local(o.tag) != "Obs":
                continue
            v = o.attrib.get("OBS_VALUE")
            try:
                value = float(v) if v not in (None, "", "NaN") else None
            except ValueError:
                value = None
            obs.append({"tp": o.attrib.get("TIME_PERIOD", ""), "value": value, "attrs": dict(o.attrib)})
        out.append({"attrs": dict(s.attrib), "obs": obs})
    return out, ds


@dataclass(frozen=True)
class ImfConcept:
    concept: str
    flow: str
    key: str
    label: str
    unit: str
    release_lag_months: int  # assumed publication lag of a reference month (an assumption, stated in outputs)
    kind: str  # "index" | "rate"


CONCEPTS: tuple[ImfConcept, ...] = (
    ImfConcept("cpi_headline", "CPI", ".CPI._T.IX.M", "Consumer price index, all items", "index", 2, "index"),
    ImfConcept(
        "cpi_food",
        "CPI",
        ".CPI.CP01.IX.M",
        "Consumer price index, food and non-alcoholic beverages",
        "index",
        2,
        "index",
    ),
    ImfConcept(
        "fx_period_avg",
        "ER",
        ".XDC_USD.PA_RT.M",
        "Exchange rate, domestic currency per US dollar, period average",
        "domestic currency per USD",
        1,
        "rate",
    ),
    ImfConcept(
        "fx_end_period",
        "ER",
        ".XDC_USD.EOP_RT.M",
        "Exchange rate, domestic currency per US dollar, end of period",
        "domestic currency per USD",
        1,
        "rate",
    ),
)
CONCEPT_BY_NAME = {c.concept: c for c in CONCEPTS}


def series_key(concept: str, iso3: str) -> str:
    return f"imf.{concept}.{iso3}"


def request_url(c: ImfConcept) -> str:
    return f"{BASE_URL}/data/IMF.STA,{c.flow}/{c.key}"


@dataclass
class Retrieval:
    concept: str
    url: str
    path: Path
    sha256: str
    bytes: int
    retrieved_at: str
    reused: bool


async def retrieve(
    http: HttpClient,
    c: ImfConcept,
    workdir: Path,
    *,
    start_period: str = DEFAULT_START,
    resume: bool = True,
    now: datetime | None = None,
) -> Retrieval:
    """Fetch one concept for every country to ``workdir/raw``. With ``resume`` a completed retrieval (the file and
    its recorded SHA-256 agree) is reused, so an interrupted refresh continues instead of starting again."""
    raw = workdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path, side = raw / f"imf_{c.concept}.xml", raw / f"imf_{c.concept}.json"
    url = request_url(c)
    if resume and path.is_file() and side.is_file():
        meta = json.loads(side.read_text())
        if meta.get("start_period") == start_period and hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]:
            return Retrieval(c.concept, url, path, meta["sha256"], meta["bytes"], meta["retrieved_at"], True)
    text = await http.get_text(url, params={"startPeriod": start_period}, use_cache=False)
    if not text.strip():
        raise ValueError(f"imf: empty response for {c.concept}")
    data = text.encode()
    digest = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    meta = {
        "concept": c.concept,
        "url": url,
        "start_period": start_period,
        "sha256": digest,
        "bytes": len(data),
        "retrieved_at": (now or datetime.now(UTC)).isoformat(),
    }
    side.write_text(json.dumps(meta, indent=1))
    return Retrieval(c.concept, url, path, digest, len(data), meta["retrieved_at"], False)


async def retrieve_all(
    http: HttpClient, workdir: Path, *, start_period: str = DEFAULT_START, resume: bool = True, pause: float = 1.0
) -> list[Retrieval]:
    out: list[Retrieval] = []
    for i, c in enumerate(CONCEPTS):
        if i:
            await asyncio.sleep(pause)  # courtesy between requests; the API is shared infrastructure
        out.append(await retrieve(http, c, workdir, start_period=start_period, resume=resume))
    return out


@dataclass
class ParsedConcept:
    observations: pd.DataFrame
    series: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    source: dict[str, Any]


def parse_concept(text: str, c: ImfConcept, retrieved_at: datetime, url: str | None = None) -> ParsedConcept:
    """Validate an SDMX StructureSpecificData message for one concept (see the module docstring for the rules)."""
    series, ds = parse_sdmx(text)
    m = _STRUCT.search(text[:4000])
    version = f"{m.group(1)}:{m.group(2)}({m.group(3)})" if m else None
    cutoff = pd.Timestamp(retrieved_at.year, retrieved_at.month, 1)
    recs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for s in series:
        a = s["attrs"]
        iso3 = str(a.get("COUNTRY", ""))
        if not _ISO3.match(iso3):
            rejected.append(
                {"series_key": f"imf.{c.concept}.{iso3}", "period": None, "value": None, "reason": "non_country_code"}
            )
            continue
        key = series_key(c.concept, iso3)
        seen: dict[pd.Timestamp, int] = {}
        valid: list[dict[str, Any]] = []
        n_empty = n_rej = 0
        for o in s["obs"]:
            tp = o["tp"]
            if not _MONTHLY.match(tp):
                rejected.append({"series_key": key, "period": tp, "value": o["value"], "reason": "non_monthly_period"})
                n_rej += 1
                continue
            period = pd.Timestamp(year=int(tp[:4]), month=int(tp[6:8]), day=1)
            if o["value"] is None:
                n_empty += 1
                continue
            v = float(o["value"])
            if period > cutoff:
                rejected.append(_rej(key, period, v, "future_period"))
                n_rej += 1
                continue
            if not v > 0:
                rejected.append(_rej(key, period, v, "non_positive_level"))
                n_rej += 1
                continue
            seen[period] = seen.get(period, 0) + 1
            valid.append(
                {
                    "series_key": key,
                    "period": period,
                    "value": v,
                    "reference_period": o["attrs"].get("REFERENCE_PERIOD") or a.get("COMMON_REFERENCE_PERIOD"),
                    "derivation": o["attrs"].get("DERIVATION_TYPE"),
                }
            )
        dup = {p for p, n in seen.items() if n > 1}
        if dup:
            for p in sorted(dup):
                rejected.append(_rej(key, p, None, "duplicate_period"))
            n_rej += len(dup)
            valid = [r for r in valid if r["period"] not in dup]
        recs.extend(valid)
        breaks: list[str] = []
        if c.kind == "index" and valid:
            lv = pd.Series([r["value"] for r in valid], index=[r["period"] for r in valid])
            rf = pd.Series([r["reference_period"] for r in valid], index=lv.index)
            breaks = [b.strftime("%Y-%m") for b in T.find_base_breaks(lv, rf)]
        periods = [r["period"] for r in valid]
        rows.append(
            {
                "series_key": key,
                "provider": "imf",
                "dataset": c.flow,
                "concept": c.concept,
                "country_iso3": iso3,
                "label": c.label,
                "unit": c.unit,
                "base_period": a.get("COMMON_REFERENCE_PERIOD"),
                "first_period": min(periods).strftime("%Y-%m") if periods else None,
                "last_period": max(periods).strftime("%Y-%m") if periods else None,
                "n_obs": len(valid),
                "n_source_empty": n_empty,
                "n_rejected": n_rej,
                "base_breaks": breaks,
                "release_lag_months": c.release_lag_months,
                "source_ref": f"IMF.STA,{c.flow}/{iso3}{c.key}",
            }
        )
    obs = pd.DataFrame(recs, columns=["series_key", "period", "value", "reference_period", "derivation"])
    source = {
        "provider": "imf",
        "dataset": c.flow,
        "concept": c.concept,
        "structure": version,
        "publication_date": ds.get("PUBLICATION_DATE"),
        "update_date": ds.get("UPDATE_DATE"),
        "request": url or request_url(c),
        "suggested_citation": ds.get("SUGGESTED_CITATION"),
        "n_series": len(rows),
        "n_observations": len(obs),
        "n_source_empty": int(sum(r["n_source_empty"] for r in rows)),
        "n_rejected": len(rejected),
    }
    return ParsedConcept(obs, rows, rejected, source)


def _rej(key: str, period: pd.Timestamp | None, value: float | None, reason: str) -> dict[str, Any]:
    return {
        "series_key": key,
        "period": period.strftime("%Y-%m") if period is not None else None,
        "value": value,
        "reason": reason,
    }


__all__ = [
    "CONCEPTS",
    "CONCEPT_BY_NAME",
    "ImfConcept",
    "ParsedConcept",
    "Retrieval",
    "parse_concept",
    "parse_sdmx",
    "retrieve",
    "retrieve_all",
    "series_key",
]
