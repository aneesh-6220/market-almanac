"""Experiment configuration (validated, serialisable, hashable)."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field, field_validator, model_validator


class ExperimentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    country_iso3: str = Field(pattern=r"^[A-Z]{3}$")
    commodity_codes: list[str] = Field(min_length=1, max_length=20)
    market_codes: list[str] | None = None
    price_types: list[str] = ["Retail"]
    units: list[str] | None = None

    horizons: list[int] = [1, 3]
    spike_threshold: float = Field(0.10, gt=0, lt=2)
    sensitivity_thresholds: list[float] = [0.05, 0.10, 0.15, 0.20]

    families: list[str] = ["A", "B", "C", "D"]
    include_trees: bool = True
    primary_regression_model: str = "ridge_B"
    primary_classification_model: str = "logit_B"

    climatology_mode: str = "expanding"
    climatology_fixed_start_year: int = 1991
    climatology_fixed_end_year: int = 2010
    climatology_min_years: int = 10

    min_train_months: int = Field(48, ge=24, le=240)
    refit_every: int = Field(12, ge=1, le=24)
    min_test_periods: int = Field(24, ge=12)
    min_test_events: int = Field(10, ge=5)
    min_series_observations: int = Field(48, ge=24)
    significance_level: float = Field(0.05, gt=0, lt=0.5)
    bootstrap_reps: int = Field(1000, ge=100, le=10000)
    seed: int = 42

    @field_validator("horizons")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        if not v or any(h < 1 or h > 12 for h in v):
            raise ValueError("horizons must be between 1 and 12 months")
        return sorted(set(v))

    @field_validator("families")
    @classmethod
    def _fam(cls, v: list[str]) -> list[str]:
        if not set(v) <= {"A", "B", "C", "D"} or "A" not in v:
            raise ValueError("families must be a subset of A-D and include the baseline family A")
        return sorted(set(v))

    @field_validator("climatology_mode")
    @classmethod
    def _clim(cls, v: str) -> str:
        if v not in ("expanding", "fixed"):
            raise ValueError("climatology_mode must be 'expanding' or 'fixed'")
        return v

    @model_validator(mode="after")
    def _primary(self) -> ExperimentConfig:
        if self.spike_threshold not in self.sensitivity_thresholds:
            self.sensitivity_thresholds = sorted({*self.sensitivity_thresholds, self.spike_threshold})
        return self

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()[:12]
