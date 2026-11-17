"""Research results: experiments, backtests, predictions, comparisons, forecasts, reports, exports."""

from __future__ import annotations

import json
from pathlib import Path as FsPath
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from shocktrace.config import Settings
from shocktrace.db import models as m
from shocktrace.reporting.report import export_bundle, markdown_report
from shocktrace_api.deps import cache, db_dep, settings_dep
from shocktrace_api.schemas import BacktestOut, ComparisonOut, ExperimentSummary, ForecastOut, Page, PredictionPoint

router = APIRouter(prefix="/api/v1")
EID = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]


def _exp(db: Session, settings: Settings, eid: str) -> m.Experiment:
    e = db.get(m.Experiment, eid)
    if e is None or e.mode != settings.shocktrace_mode.value:
        raise HTTPException(404, f"experiment {eid} not found")
    return e


def _summary(e: m.Experiment) -> ExperimentSummary:
    return ExperimentSummary(
        id=e.id,
        name=e.name,
        mode=e.mode,
        created_at=e.created_at,
        status=e.status,
        synthetic=e.synthetic,
        country_iso3=e.country_iso3,
        commodity_codes=e.commodity_codes,
        verdict=e.verdict,
        statement=(e.conclusion or {}).get("statement"),
        n_series=e.n_series,
        config_hash=e.config_hash,
        evidence_class=e.evidence_class or "exploratory",
        study=e.study,
        variant=e.variant or "primary",
        method_revision=e.method_revision,
        price_release_lag_months=int((e.config or {}).get("price_release_lag_months", 0)),
        superseded_by=e.superseded_by,
        superseded_reason=e.superseded_reason,
        current=e.superseded_by is None,
    )


def _current(q: Any, include_superseded: bool, all_variants: bool = False) -> Any:
    """Restrict a query joined to Experiment to scientifically current primary runs by default."""
    if not include_superseded:
        q = q.where(m.Experiment.superseded_by.is_(None))
    if not all_variants:
        q = q.where(m.Experiment.variant == "primary")
    return q


@router.get("/experiments", response_model=list[ExperimentSummary], tags=["research"])
def experiments(
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    study: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_.\-]{1,80}$")] = None,
    evidence_class: Annotated[str | None, Query(pattern="^(exploratory|confirmatory)$")] = None,
    include_superseded: Annotated[
        bool, Query(description="Also return runs replaced by a later method revision (hidden by default).")
    ] = False,
    all_variants: Annotated[
        bool, Query(description="Also return sensitivity and falsification variants (primary runs only by default).")
    ] = False,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[ExperimentSummary]:
    """Experiments, newest first. Defaults to scientifically current primary runs."""
    q = _current(
        select(m.Experiment).where(m.Experiment.mode == settings.shocktrace_mode.value),
        include_superseded,
        all_variants,
    )
    if country:
        q = q.where(m.Experiment.country_iso3 == country)
    if study:
        q = q.where(m.Experiment.study == study)
    if evidence_class:
        q = q.where(m.Experiment.evidence_class == evidence_class)
    return [_summary(e) for e in db.scalars(q.order_by(desc(m.Experiment.created_at)).limit(500))]


@router.get("/experiments/{experiment_id}", tags=["research"])
def experiment(
    experiment_id: EID, db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)
) -> dict[str, Any]:
    e = _exp(db, settings, experiment_id)
    res = cache.results(e.artifact_dir)
    return {"summary": _summary(e).model_dump(mode="json"), "results": res}


@router.get("/backtests", response_model=list[BacktestOut], tags=["research"])
def backtests(
    experiment_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_\-]{1,64}$")] = None,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[BacktestOut]:
    q = select(m.BacktestRun).join(m.Experiment).where(m.Experiment.mode == settings.shocktrace_mode.value)
    if experiment_id:
        q = q.where(m.BacktestRun.experiment_id == experiment_id)
    return [BacktestOut(**{c: getattr(b, c) for c in BacktestOut.model_fields}) for b in db.scalars(q.limit(500))]


@router.get("/backtests/{backtest_id}", tags=["research"])
def backtest(
    backtest_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-:]{1,100}$")],
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    b = db.get(m.BacktestRun, backtest_id)
    if b is None:
        raise HTTPException(404, "backtest not found")
    _exp(db, settings, b.experiment_id)
    evals = db.scalars(select(m.ModelEvaluation).where(m.ModelEvaluation.backtest_id == backtest_id))
    return {
        "backtest": BacktestOut(**{c: getattr(b, c) for c in BacktestOut.model_fields}).model_dump(),
        "folds": b.folds,
        "models": {e.model: e.metrics for e in evals},
    }


@router.get("/predictions", response_model=Page[PredictionPoint], tags=["research"])
def predictions(
    experiment_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9_\-]{1,64}$")],
    task: Annotated[str, Query(pattern="^(regression|classification)$")] = "regression",
    horizon: Annotated[int, Query(ge=1, le=12)] = 1,
    series_id: Annotated[str | None, Query(pattern=r"^ps_[0-9a-f]{16}$")] = None,
    models: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_,]{1,200}$")] = None,
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> Page[PredictionPoint]:
    e = _exp(db, settings, experiment_id)
    p = FsPath(e.artifact_dir) / "predictions.parquet"
    if not p.exists():
        raise HTTPException(404, "no predictions stored for this experiment")
    df = pd.read_parquet(p)
    df = df[(df["task"] == task) & (df["horizon"] == horizon)]
    if task == "classification":
        thr = (e.config or {}).get("spike_threshold")
        df = df[np.isclose(df["threshold"].astype(float), float(thr))] if thr is not None else df
    if series_id:
        df = df[df["series_id"] == series_id]
    if models:
        df = df[df["model"].isin(models.split(","))]
    df = df.sort_values(["series_id", "origin", "model"])
    page = df.iloc[offset : offset + limit]

    def f(v: Any) -> float | None:
        return float(v) if v is not None and np.isfinite(v) else None

    items = [
        PredictionPoint(
            series_id=r.series_id,
            origin=pd.Timestamp(r.origin).date().isoformat(),
            target_period=pd.Timestamp(r.target_period).date().isoformat(),
            model=r.model,
            y=f(r.y),
            pred=f(r.pred),
            fold=int(r.fold),
        )
        for r in page.itertuples()
    ]
    return Page[PredictionPoint](items=items, total=len(df), limit=limit, offset=offset, synthetic=e.synthetic)


@router.get("/model-comparisons", response_model=list[ComparisonOut], tags=["research"])
def model_comparisons(
    experiment_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_\-]{1,64}$")] = None,
    role: Annotated[
        str | None,
        Query(pattern="^(primary|primary_production|production_vs_local|secondary|specification|vs_baseline)$"),
    ] = None,
    include_superseded: bool = False,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[ComparisonOut]:
    """Model comparisons. Without ``experiment_id`` only current primary runs are included."""
    q = select(m.ModelComparison).join(m.Experiment).where(m.Experiment.mode == settings.shocktrace_mode.value)
    if experiment_id:
        q = q.where(m.ModelComparison.experiment_id == experiment_id)
    else:
        q = _current(q, include_superseded)
    if role:
        q = q.where(m.ModelComparison.role == role)
    return [ComparisonOut(**{c: getattr(r, c) for c in ComparisonOut.model_fields}) for r in db.scalars(q.limit(1000))]


def _forecast_out(f: m.Forecast, synthetic: bool) -> ForecastOut:
    return ForecastOut(**{c: getattr(f, c) for c in ForecastOut.model_fields if c != "synthetic"}, synthetic=synthetic)


@router.get("/forecasts", response_model=list[ForecastOut], tags=["research"])
def forecasts(
    series_id: Annotated[str | None, Query(pattern=r"^ps_[0-9a-f]{16}$")] = None,
    experiment_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_\-]{1,64}$")] = None,
    status: Annotated[str | None, Query(pattern="^(issued|withheld)$")] = None,
    include_superseded: bool = False,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[ForecastOut]:
    """Forecast records. Without ``experiment_id`` only forecasts of current primary runs are returned."""
    q = select(m.Forecast).where(m.Forecast.mode == settings.shocktrace_mode.value)
    if series_id:
        q = q.where(m.Forecast.series_id == series_id)
    if experiment_id:
        q = q.where(m.Forecast.experiment_id == experiment_id)
    else:
        q = _current(q.join(m.Experiment, m.Experiment.id == m.Forecast.experiment_id), include_superseded)
    if status:
        q = q.where(m.Forecast.status == status)
    synthetic = settings.shocktrace_mode.value == "demo"
    return [
        _forecast_out(f, synthetic)
        for f in db.scalars(q.order_by(m.Forecast.series_id, m.Forecast.task, m.Forecast.horizon).limit(2000))
    ]


@router.get("/forecasts/{forecast_id}", response_model=ForecastOut, tags=["research"])
def forecast(
    forecast_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-:]{1,200}$")],
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> ForecastOut:
    f = db.get(m.Forecast, forecast_id)
    if f is None or f.mode != settings.shocktrace_mode.value:
        raise HTTPException(404, "forecast not found")
    return _forecast_out(f, settings.shocktrace_mode.value == "demo")


@router.get("/reports/{experiment_id}", tags=["output"], response_class=PlainTextResponse)
def report(
    experiment_id: EID, db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)
) -> PlainTextResponse:
    e = _exp(db, settings, experiment_id)
    return PlainTextResponse(markdown_report(cache.results(e.artifact_dir)), media_type="text/markdown; charset=utf-8")


@router.get("/exports/{experiment_id}", tags=["output"])
def export(
    experiment_id: EID,
    format: Annotated[str, Query(pattern="^(zip|json|csv|manifest)$")] = "zip",
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    e = _exp(db, settings, experiment_id)
    d = FsPath(e.artifact_dir)
    tag = "SYNTHETIC_" if e.synthetic else ""
    if format == "zip":
        return Response(
            export_bundle(d),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="shocktrace_{tag}{e.id}.zip"'},
        )
    if format == "json":
        return Response(
            json.dumps(cache.results(e.artifact_dir)),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="shocktrace_{tag}{e.id}.json"'},
        )
    if format == "manifest":
        return Response((d / "manifest.json").read_text(), media_type="application/json")
    p = d / "predictions.parquet"
    if not p.exists():
        raise HTTPException(404, "no predictions stored")
    return Response(
        pd.read_parquet(p).to_csv(index=False),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="shocktrace_{tag}{e.id}_predictions.csv"'},
    )
