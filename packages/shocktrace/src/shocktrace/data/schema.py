"""Canonical (normalized) dataset schemas.

Every provider normalizes into one of these frames. Synthetic demo data obeys exactly
the same schemas and validation rules as real data.

Time semantics used throughout ShockTrace (see docs/DATA_DICTIONARY.md):

* ``period``        – the observation period (first day of the month, or Jan 1 for annual).
* ``published_at``  – when the source *released* the value, if known. Null when unknown;
                      it is never back-filled from ``retrieved_at``.
* ``retrieved_at``  – when ShockTrace fetched the record (UTC).
* information cutoff – defined per forecast; see ``shocktrace.data.alignment``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class FrameSchema:
    name: str
    columns: dict[str, str]  # column -> logical dtype: str|float|int|date|datetime|bool
    required_non_null: tuple[str, ...]
    key: tuple[str, ...]
    description: str = ""
    optional: tuple[str, ...] = field(default_factory=tuple)


PRICES = FrameSchema(
    name="prices",
    description="Monthly market-commodity price observations (WFP via HDX HAPI, or synthetic demo).",
    columns={
        "series_id": "str",
        "provider": "str",
        "country_iso3": "str",
        "admin1_name": "str",
        "admin2_name": "str",
        "market_code": "str",
        "market_name": "str",
        "lat": "float",
        "lon": "float",
        "commodity_code": "str",
        "commodity_name": "str",
        "commodity_category": "str",
        "unit": "str",
        "price_type": "str",
        "price_flag": "str",
        "currency": "str",
        "period": "date",
        "price": "float",
        "source_ref": "str",
        "reference_period_start": "datetime",
        "reference_period_end": "datetime",
        "published_at": "datetime",
        "retrieved_at": "datetime",
        "quality_flags": "str",
    },
    required_non_null=(
        "series_id",
        "provider",
        "country_iso3",
        "market_code",
        "commodity_code",
        "unit",
        "price_type",
        "currency",
        "period",
        "price",
        "retrieved_at",
    ),
    key=("series_id", "period"),
)

WEATHER_MONTHLY = FrameSchema(
    name="weather_monthly",
    description="Monthly aggregates of NASA POWER daily point data at a market-local grid cell (geographic proxy).",
    columns={
        "location_id": "str",
        "provider": "str",
        "lat": "float",
        "lon": "float",
        "period": "date",
        "precip_total_mm": "float",
        "t2m_mean_c": "float",
        "t2m_max_mean_c": "float",
        "t2m_min_mean_c": "float",
        "heat_days_t2m_max_ge_35c": "float",
        "days_observed": "int",
        "days_in_month": "int",
        "complete": "bool",
        "time_standard": "str",
        "spatial_basis": "str",
        "retrieved_at": "datetime",
    },
    required_non_null=("location_id", "provider", "period", "days_observed", "retrieved_at"),
    key=("location_id", "period"),
)

MACRO = FrameSchema(
    name="macro",
    description="Macroeconomic indicators (IMF SDMX monthly; World Bank annual).",
    columns={
        "provider": "str",
        "country_iso3": "str",
        "indicator_code": "str",
        "indicator_name": "str",
        "frequency": "str",  # M | A
        "period": "date",
        "value": "float",
        "unit": "str",
        "source_ref": "str",
        "published_at": "datetime",
        "retrieved_at": "datetime",
        "quality_flags": "str",
    },
    required_non_null=("provider", "country_iso3", "indicator_code", "frequency", "period", "retrieved_at"),
    key=("provider", "country_iso3", "indicator_code", "period"),
)

AGRICULTURE = FrameSchema(
    name="agriculture",
    description="Annual country-level agricultural statistics (FAOSTAT QCL).",
    columns={
        "provider": "str",
        "country_iso3": "str",
        "fao_area_code": "str",
        "domain_code": "str",
        "item_code": "str",
        "item_name": "str",
        "element_code": "str",
        "element_name": "str",
        "unit": "str",
        "year": "int",
        "value": "float",
        "flag": "str",
        "flag_description": "str",
        "source_ref": "str",
        "published_at": "datetime",
        "retrieved_at": "datetime",
    },
    required_non_null=("provider", "country_iso3", "item_code", "element_code", "year", "retrieved_at"),
    key=("provider", "country_iso3", "item_code", "element_code", "year"),
)

COUNTRIES = FrameSchema(
    name="countries",
    description="Country metadata.",
    columns={
        "iso3": "str",
        "name": "str",
        "region": "str",
        "income_level": "str",
        "provider": "str",
        "retrieved_at": "datetime",
    },
    required_non_null=("iso3", "name", "provider"),
    key=("iso3",),
)

SCHEMAS = {s.name: s for s in (PRICES, WEATHER_MONTHLY, MACRO, AGRICULTURE, COUNTRIES)}


class SchemaError(ValueError):
    """A frame does not satisfy its canonical schema."""


def empty_frame(schema: FrameSchema) -> pd.DataFrame:
    return coerce(pd.DataFrame({c: [] for c in schema.columns}), schema)


def coerce(df: pd.DataFrame, schema: FrameSchema) -> pd.DataFrame:
    """Coerce columns to their logical dtypes; add missing optional columns as null."""
    out = df.copy()
    for col, typ in schema.columns.items():
        if col not in out.columns:
            out[col] = pd.NA
        if typ == "str":
            out[col] = out[col].astype("string")
        elif typ == "float":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
        elif typ == "int":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
        elif typ == "bool":
            out[col] = out[col].astype("boolean")
        elif typ == "date":
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.normalize()
        elif typ == "datetime":
            s = pd.to_datetime(out[col], errors="coerce", utc=True)
            out[col] = s
    return out[list(schema.columns)]


def validate(df: pd.DataFrame, schema: FrameSchema, *, allow_duplicate_keys: bool = False) -> list[str]:
    """Validate a frame. Raises SchemaError on structural problems; returns warnings."""
    missing = [c for c in schema.columns if c not in df.columns]
    if missing:
        raise SchemaError(f"{schema.name}: missing columns {missing}")
    problems: list[str] = []
    for col in schema.required_non_null:
        n = int(df[col].isna().sum())
        if n:
            raise SchemaError(f"{schema.name}: {n} null values in required column '{col}'")
    if not allow_duplicate_keys and len(df):
        dups = int(df.duplicated(list(schema.key)).sum())
        if dups:
            raise SchemaError(f"{schema.name}: {dups} duplicate rows on key {schema.key}")
    if "period" in df.columns and schema.columns.get("period") == "date" and len(df):
        p = pd.to_datetime(df["period"])
        if not (p.dt.day == 1).all():
            raise SchemaError(f"{schema.name}: 'period' must be the first day of a month")
    extra = [c for c in df.columns if c not in schema.columns]
    if extra:
        problems.append(f"{schema.name}: unexpected extra columns ignored: {extra}")
    return problems
