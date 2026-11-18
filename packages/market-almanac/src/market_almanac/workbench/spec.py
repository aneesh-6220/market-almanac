"""Versioned, validated research specifications.

A research specification states *what is being estimated or predicted, on which population,
with which design and inference, before any result is seen*. It is written as YAML or JSON,
validated here, frozen (hashed and recorded with the git revision and data snapshots), executed,
packaged and re-executed. Contradictory or scientifically unsupported configurations fail with
an explanation instead of running.

Design limits that are enforced, not merely documented:

* predictive studies are always evaluated on rolling forecast origins; random train/test
  splits are rejected for time series;
* every predictive hypothesis compares a model against the price-history baseline family A
  (or one family against another) on a common set of forecasts;
* a confirmatory study needs pre-declared hypotheses, a multiplicity correction for more than
  one hypothesis, a test-period start and a frozen specification;
* "causal" designs are refused: this release implements no estimator with identification
  diagnostics, and an associational or predictive result must not be presented as causal.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = "ma-research-spec/1"
FAMILIES = ("A", "B", "C", "D")
FAMILY_MEANING = {
    "A": "price history only (lags, momentum, volatility, seasonality)",
    "B": "A + market-local weather anomalies (NASA POWER at the market's grid cell)",
    "C": "B + national macroeconomic indicators (IMF / World Bank)",
    "D": "C + annual national crop production (FAOSTAT)",
}
ROBUSTNESS = (
    "price_lag_0",  # prices usable in the month they describe
    "price_lag_2",  # two-month publication delay
    "raw_precipitation",  # without the daily precipitation plausibility screen
    "weather_lag_1",  # weather available one month late
    "leave_one_country_out",  # pooled result recomputed without each country
    "drop_top3_months",  # influence of the three most influential origin months
)
NEGATIVE_CONTROLS = (
    "weather_time_shift_60",  # weather from 60 months earlier: no contemporaneous information
    "weather_permuted_cells",  # each market receives another country's grid cell
)
DESCRIPTIVE_STATS = ("trend", "seasonality", "volatility", "dispersion", "comovement", "anomalies")
ASSOC_EXPOSURES = ("rain_anom", "t2m_anom", "rain_anom_abs")
SLUG = r"^[a-z0-9][a-z0-9\-]{2,63}$"


class SpecError(ValueError):
    """A specification that is invalid or scientifically contradictory."""


class Population(BaseModel):
    model_config = ConfigDict(extra="forbid")

    countries: list[str] = Field(min_length=1, max_length=120)
    exclude_countries: list[str] = []
    commodity_codes: list[str] | None = None
    commodity_name_contains: list[str] | None = Field(None, description="case-insensitive name filters, e.g. maize")
    commodity_categories: list[str] | None = Field(
        None, description="WFP commodity categories, e.g. 'cereals and tubers' (exact, case-insensitive)"
    )
    price_types: list[str] = ["Retail"]
    min_observations: int = Field(48, ge=24, le=240)
    min_coverage: float = Field(0.8, gt=0, le=1)
    max_gap_months: int = Field(6, ge=0, le=24)
    require_coordinates: bool = True
    min_eligible_series_per_group: int = Field(5, ge=1, le=100)
    max_groups_per_country: int = Field(3, ge=1, le=20)
    selection_rule: str = Field(
        "per country, the commodity groups with the most eligible series (ties by commodity code); "
        "eligibility is computed from metadata only (counts, coverage, gaps), never from model performance",
        max_length=400,
    )

    @field_validator("countries", "exclude_countries")
    @classmethod
    def _iso(cls, v: list[str]) -> list[str]:
        out = sorted({c.strip().upper() for c in v})
        bad = [c for c in out if not re.fullmatch(r"[A-Z]{3}", c)]
        if bad:
            raise ValueError(f"not ISO3 codes: {bad}")
        return out


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_release_lag_months: int = Field(1, ge=0, le=2)
    weather_release_lag_months: int = Field(0, ge=0, le=3)
    vintage_statement: str = Field(
        "Backtests use today's revised data; original publication dates are not available from the providers, so "
        "information timing is an explicitly assumed release lag, not an observed real-time vintage.",
        max_length=600,
    )


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^H[0-9]{1,2}[a-z]?$")
    statement: str = Field(min_length=10, max_length=400)
    challenger: str = Field(pattern=r"^[ABCD]$")
    baseline: str = Field(pattern=r"^[ABCD]$")
    horizon: int = Field(ge=1, le=12)
    alternative: Literal["challenger_better", "two_sided"] = "challenger_better"


class Predictive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["log_change"] = "log_change"
    horizons: list[int] = [1, 3]
    families: list[str] = ["A", "B"]
    evaluation: Literal["rolling_origin", "random_split"] = "rolling_origin"
    min_train_months: int = Field(48, ge=24, le=240)
    refit_every: int = Field(12, ge=1, le=24)
    test_start: date | None = Field(None, description="first forecast origin of the evaluation sample")
    include_tree_models: bool = False
    hypotheses: list[Hypothesis] = []
    loss_aggregation: Literal["country_balanced", "series_pooled"] = "country_balanced"
    min_test_periods: int = Field(24, ge=12, le=240)

    @field_validator("horizons")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        if not v or any(h < 1 or h > 12 for h in v):
            raise ValueError("horizons must be between 1 and 12 months")
        return sorted(set(v))

    @field_validator("families")
    @classmethod
    def _f(cls, v: list[str]) -> list[str]:
        v = sorted(set(v))
        if not set(v) <= set(FAMILIES):
            raise ValueError(f"families must be a subset of {FAMILIES}")
        return v


class Associational(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["dlog_price_1"] = "dlog_price_1"
    exposure: str = "rain_anom"
    exposure_lags: list[int] = [1, 2, 3]
    fixed_effects: list[Literal["series", "calendar_month", "country_period"]] = ["series", "calendar_month"]
    standard_errors: Literal["cluster_series", "cluster_period", "two_way"] = "cluster_series"

    @field_validator("exposure")
    @classmethod
    def _e(cls, v: str) -> str:
        if v not in ASSOC_EXPOSURES:
            raise ValueError(f"exposure must be one of {ASSOC_EXPOSURES}")
        return v

    @field_validator("exposure_lags")
    @classmethod
    def _l(cls, v: list[int]) -> list[int]:
        if not v or any(lag < 0 or lag > 12 for lag in v):
            raise ValueError("exposure lags must be between 0 and 12")
        return sorted(set(v))


class Descriptive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statistics: list[str] = list(DESCRIPTIVE_STATS)
    period_start: date | None = None
    period_end: date | None = None

    @field_validator("statistics")
    @classmethod
    def _s(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in DESCRIPTIVE_STATS]
        if bad:
            raise ValueError(f"unknown descriptive statistics {bad}; choose from {DESCRIPTIVE_STATS}")
        return v


class Inference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpha: float = Field(0.05, gt=0, lt=0.5)
    multiplicity: Literal["holm", "benjamini_hochberg", "none"] = "holm"
    test: Literal["diebold_mariano_hac"] = "diebold_mariano_hac"
    unit_of_inference: str = Field(
        "forecast-origin month: losses are averaged within each month before testing, so thousands of "
        "market-month forecasts are not treated as independent observations",
        max_length=400,
    )
    bootstrap: Literal["two_way_country_month", "moving_block_months", "country_cluster", "none"] = (
        "two_way_country_month"
    )
    bootstrap_reps: int = Field(1000, ge=200, le=10000)


class Compute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_groups: int = Field(200, ge=1, le=1000)
    max_series: int = Field(20000, ge=1, le=200000)
    max_runtime_minutes: int = Field(240, ge=1, le=2880)


class ResearchSpec(BaseModel):
    """A complete, typed research specification (see module docstring for enforced rules)."""

    model_config = ConfigDict(extra="forbid")

    spec_version: Literal["ma-research-spec/1"] = "ma-research-spec/1"
    id: str = Field(pattern=SLUG)
    title: str = Field(min_length=5, max_length=160)
    question: str = Field(min_length=10, max_length=1000)
    hypothesis: str = Field(min_length=10, max_length=2000)
    estimand: str = Field(min_length=10, max_length=1000)
    study_type: Literal["descriptive", "associational", "predictive", "causal"]
    evidence_class: Literal["exploratory", "confirmatory"] = "exploratory"
    population: Population
    timing: Timing = Timing()
    predictive: Predictive | None = None
    associational: Associational | None = None
    descriptive: Descriptive | None = None
    inference: Inference = Inference()
    robustness: list[str] = []
    negative_controls: list[str] = []
    seed: int = 20261117
    compute: Compute = Compute()
    limitations: list[str] = []
    authors: list[str] = []

    @field_validator("robustness")
    @classmethod
    def _rob(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in ROBUSTNESS]
        if bad:
            raise ValueError(f"unknown robustness checks {bad}; available: {ROBUSTNESS}")
        return v

    @field_validator("negative_controls")
    @classmethod
    def _neg(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in NEGATIVE_CONTROLS]
        if bad:
            raise ValueError(f"unknown negative controls {bad}; available: {NEGATIVE_CONTROLS}")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> ResearchSpec:
        problems = coherence_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # --- identity -----------------------------------------------------------------------------
    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def spec_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def coherence_problems(s: ResearchSpec) -> list[str]:
    """Scientific contradictions, each with the reason (empty list when coherent)."""
    p: list[str] = []
    if s.study_type == "causal":
        p.append(
            "causal designs are not supported: no estimator with identification assumptions and diagnostics is "
            "implemented in this release; specify an associational or predictive study and interpret it as such"
        )
        return p
    blocks = {"predictive": s.predictive, "associational": s.associational, "descriptive": s.descriptive}
    if blocks[s.study_type] is None:
        p.append(f"study_type '{s.study_type}' needs a '{s.study_type}' block")
    for name, blk in blocks.items():
        if name != s.study_type and blk is not None:
            p.append(f"a '{name}' block contradicts study_type '{s.study_type}'")
    causal_words = re.compile(r"\b(causal effect|causes|caused by|impact of .* on)\b", re.I)
    if causal_words.search(s.estimand) or causal_words.search(s.question):
        p.append(
            "the question or estimand uses causal language, but the design is not causal; "
            "describe a prediction or an association instead"
        )
    overlap = set(s.population.countries) & set(s.population.exclude_countries)
    if overlap:
        p.append(f"countries both included and excluded: {sorted(overlap)}")

    if s.study_type == "predictive" and s.predictive is not None:
        pr = s.predictive
        if pr.evaluation != "rolling_origin":
            p.append(
                "random train/test splits leak future information into training for time series; "
                "predictive studies use rolling forecast origins"
            )
        if "A" not in pr.families:
            p.append("the price-history baseline family A must be estimated: every model is judged against it")
        if max(pr.horizons) + s.timing.price_release_lag_months > 12:
            p.append("horizon plus price release lag may not exceed 12 months")
        if any(f in pr.families for f in ("B", "C", "D")) and not s.population.require_coordinates:
            p.append("weather families need market coordinates; set population.require_coordinates to true")
        for h in pr.hypotheses:
            if h.challenger == h.baseline:
                p.append(f"{h.id}: challenger and baseline are the same family")
            if h.challenger not in pr.families or h.baseline not in pr.families:
                p.append(f"{h.id}: compares families that are not estimated ({h.challenger} vs {h.baseline})")
            if h.horizon not in pr.horizons:
                p.append(f"{h.id}: horizon {h.horizon} is not among the evaluated horizons {pr.horizons}")
        ids = [h.id for h in pr.hypotheses]
        if len(ids) != len(set(ids)):
            p.append("hypothesis ids must be unique")
        if s.evidence_class == "confirmatory":
            if not pr.hypotheses:
                p.append("a confirmatory study must pre-declare its hypotheses")
            if len(pr.hypotheses) > 1 and s.inference.multiplicity == "none":
                p.append("several confirmatory hypotheses need a multiplicity correction (holm or benjamini_hochberg)")
            if pr.test_start is None:
                p.append("a confirmatory study must state the first evaluation origin (predictive.test_start)")
        if s.inference.bootstrap in ("country_cluster", "two_way_country_month") and len(s.population.countries) < 5:
            p.append("a bootstrap over countries needs at least 5 countries; use moving_block_months")
    if s.study_type == "associational" and s.evidence_class == "confirmatory" and not s.robustness:
        p.append("a confirmatory associational study must declare robustness checks")
    if s.study_type == "descriptive" and s.evidence_class == "confirmatory":
        p.append("descriptive summaries test no hypothesis; use evidence_class 'exploratory'")
    if any(n.startswith("weather_") for n in s.negative_controls) and s.study_type not in ("predictive",):
        p.append("weather negative controls apply to predictive studies")
    return p


def load_spec(path: Path | str) -> ResearchSpec:
    """Read a YAML or JSON specification and validate it (raises SpecError with every problem)."""
    text = Path(path).read_text()
    return parse_spec(text)


def parse_spec(text: str) -> ResearchSpec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"not valid YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError("a specification must be a mapping")
    try:
        return ResearchSpec.model_validate(data)
    except ValueError as exc:
        raise SpecError(_explain(exc)) from exc


def _explain(exc: ValueError) -> str:
    errs = getattr(exc, "errors", None)
    if not callable(errs):
        return str(exc)
    lines = []
    for e in errs():
        loc = ".".join(str(x) for x in e.get("loc", ())) or "spec"
        msg = str(e.get("msg", "")).removeprefix("Value error, ")
        lines.append(f"{loc}: {msg}")
    return "\n".join(lines)


def spec_summary(s: ResearchSpec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id,
        "title": s.title,
        "study_type": s.study_type,
        "evidence_class": s.evidence_class,
        "spec_hash": s.spec_hash(),
        "countries": len(s.population.countries),
    }
    if s.predictive:
        out["families"] = {f: FAMILY_MEANING[f] for f in s.predictive.families}
        out["hypotheses"] = [h.model_dump() for h in s.predictive.hypotheses]
    return out
