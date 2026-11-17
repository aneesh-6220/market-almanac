"""ShockTrace command-line interface."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from shocktrace import __version__
from shocktrace.config import RunMode, get_settings, reset_settings_cache
from shocktrace.logging import configure_logging

app = typer.Typer(help="ShockTrace: from environmental signals to economic risk.", no_args_is_help=True)


def _settings(mode: str | None = None):  # type: ignore[no-untyped-def]
    if mode:
        os.environ["SHOCKTRACE_MODE"] = mode
        reset_settings_cache()
    s = get_settings()
    configure_logging(s.log_level)
    return s


ModeOpt = Annotated[str | None, typer.Option("--mode", help="demo | live (overrides SHOCKTRACE_MODE)")]


def _echo_json(obj: object) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


@app.command()
def sources(mode: ModeOpt = None) -> None:
    """List data providers, their credentials state and licensing (no network calls)."""
    from shocktrace.providers import build_providers

    s = _settings(mode)
    for pid, p in build_providers(s).items():
        state = "configured" if p.is_configured() else "NOT CONFIGURED"
        if pid == "faostat":
            state = p.credential_state()  # type: ignore[attr-defined]
        typer.echo(f"{pid:12s} {p.info.name:32s} auth={p.info.auth.value:15s} {state}")
        typer.echo(f"{'':12s} {p.info.attribution}")


@app.command()
def doctor(
    mode: ModeOpt = None, live: Annotated[bool, typer.Option(help="also run live provider health checks")] = False
) -> None:
    """Check the local environment, database, storage and (optionally) provider connectivity."""
    from sqlalchemy import text

    from shocktrace.db.session import get_engine

    s = _settings(mode)
    ok = True
    typer.echo(f"ShockTrace {__version__} · Python {platform.python_version()} · mode={s.shocktrace_mode.value}")
    try:
        s.lake_dir.mkdir(parents=True, exist_ok=True)
        (s.lake_dir / ".write_test").write_text("ok")
        (s.lake_dir / ".write_test").unlink()
        typer.echo(f"✓ data directory writable: {s.lake_dir}")
    except OSError as exc:
        typer.secho(f"✗ data directory not writable: {exc}", fg="red")
        ok = False
    try:
        with get_engine(s.database_url).connect() as c:
            c.execute(text("SELECT 1"))
        typer.echo(f"✓ database reachable: {s.redacted_database_url()}")
    except Exception as exc:
        typer.secho(f"✗ database unreachable ({s.redacted_database_url()}): {type(exc).__name__}", fg="red")
        ok = False
    has_hdx = s.hdx_hapi_app_identifier is not None
    typer.echo(f"{'✓' if has_hdx else '·'} HDX_HAPI_APP_IDENTIFIER {'set' if has_hdx else 'not set'}")
    from shocktrace.providers import build_providers

    fao_ok = build_providers(s)["faostat"].is_configured()
    if fao_ok:
        fao_state = "✓ FAOSTAT credentials usable"
    elif s.faostat_access_token or s.faostat_username:
        fao_state = (
            "· FAOSTAT credentials present but not usable (token expired?); public bulk download fallback available"
        )
    else:
        fao_state = "· FAOSTAT credentials not set; public bulk download fallback available"
    typer.echo(fao_state)
    if live:
        from shocktrace.services import check_health

        for r in asyncio.run(check_health(s)):
            color = "green" if r.status.value == "healthy" else "yellow"
            typer.secho(f"  {r.provider_id:12s} {r.status.value:15s} {r.latency_ms or '':>8} ms  {r.message}", fg=color)
    raise typer.Exit(0 if ok else 1)


@app.command("db-init")
def db_init(mode: ModeOpt = None) -> None:
    """Create database tables (SQLite) or run Alembic migrations (PostgreSQL)."""
    s = _settings(mode)
    if s.database_url.startswith("sqlite"):
        from shocktrace.services import init_db

        init_db(s)
    else:
        from alembic import command
        from alembic.config import Config

        import shocktrace.db as dbpkg

        ini = Path.cwd() / "alembic.ini"
        cfg = Config(str(ini)) if ini.exists() else Config()
        # Migrations ship inside the package, so this works from a source checkout or an installed wheel.
        cfg.set_main_option("script_location", str(Path(dbpkg.__file__).resolve().parent / "migrations"))
        command.upgrade(cfg, "head")
    from shocktrace.services import sync_sources

    sync_sources(s)
    typer.echo(f"database ready: {s.redacted_database_url()}")


@app.command("demo-seed")
def demo_seed(skip_experiments: bool = False) -> None:
    """Generate SYNTHETIC demo data, quality report and demo experiments (no network)."""
    s = _settings("demo")
    from shocktrace.services import seed_demo

    res = seed_demo(s, run_experiments=not skip_experiments)
    typer.echo("Seeded SYNTHETIC demo data.")
    _echo_json(res)


@app.command()
def discover(
    country: Annotated[str, typer.Option(help="ISO3 country code")],
    price_type: str = "Retail",
    top: int = 15,
    mode: ModeOpt = None,
) -> None:
    """Fetch a country's WFP prices (live) and rank market-commodity groups by forecasting evidence."""
    s = _settings(mode)
    from shocktrace.services import discover_candidates, ingest_prices, store_for

    if s.shocktrace_mode == RunMode.LIVE:
        outs = asyncio.run(ingest_prices(s, country.upper(), price_type=price_type))
        for o in outs:
            typer.echo(f"ingest {o.job_id}: {o.status} rows={o.rows} {o.error or ''}")
    prices = store_for(s).read("prices")
    prices = prices[(prices["country_iso3"] == country.upper()) & (prices["price_type"] == price_type)]
    ranking = discover_candidates(prices)
    if ranking.empty:
        typer.echo("no series found")
        raise typer.Exit(1)
    typer.echo(ranking.head(top).to_string(index=False))


@app.command()
def ingest(
    source: Annotated[str, typer.Option(help="prices | weather | macro | agriculture | all")],
    country: Annotated[str, typer.Option(help="ISO3 country code")],
    commodity: Annotated[list[str] | None, typer.Option(help="commodity code(s), prices only")] = None,
    start_date: str | None = None,
    end_date: str | None = None,
    weather_start: str = "1991-01-01",
    bulk: Annotated[bool, typer.Option(help="FAOSTAT: use public bulk download instead of the API")] = False,
    production_cells: Annotated[
        bool, typer.Option(help="weather: also fetch the country's crop-production cells (MapSPAM weights)")
    ] = False,
    mode: ModeOpt = None,
) -> None:
    """Ingest live data from providers into a new immutable snapshot (idempotent)."""
    from shocktrace import services as sv

    s = _settings(mode or "live")
    iso3 = country.upper()
    outcomes = []
    if source in ("prices", "all"):
        outcomes += asyncio.run(sv.ingest_prices(s, iso3, commodity or None, start_date, end_date))
    if source in ("weather", "all"):
        outcomes.append(
            asyncio.run(
                sv.ingest_weather(
                    s, iso3, start=date.fromisoformat(weather_start), include_production_cells=production_cells
                )
            )
        )
    if source in ("macro", "all"):
        outcomes += asyncio.run(sv.ingest_macro(s, iso3))
    if source in ("agriculture", "all"):
        outcomes += asyncio.run(sv.ingest_agriculture(s, iso3, use_bulk=bulk or None))
    failed = 0
    for o in outcomes:
        failed += o.status != "succeeded"
        typer.echo(f"{o.job_id} {o.status:9s} rows={o.rows} snapshot={o.snapshot_id} {o.error or ''}")
        for w in o.warnings[:5]:
            typer.echo(f"   warning: {w}")
    raise typer.Exit(1 if failed and failed == len(outcomes) else 0)


@app.command()
def validate(mode: ModeOpt = None, show_series: bool = False) -> None:
    """Run data-quality checks on the current snapshots and store the report."""
    s = _settings(mode)
    from shocktrace.services import run_quality

    rep = run_quality(s)
    _echo_json({"id": rep["id"], "summary": rep["summary"], "consistency_issues": rep["consistency_issues"][:20]})
    if show_series:
        for x in rep["series"]:
            typer.echo(
                f"{'✓' if x['eligible'] else '✗'} {x['market_name'][:28]:28s} {x['commodity_name'][:28]:28s} "
                f"{x['unit']:8s} n={x['n_observations']:4d} cov={x['coverage']:.0%} {'; '.join(x['reasons'])}"
            )


def _cfg(
    name: str,
    country: str,
    commodity: list[str],
    horizons: list[int],
    threshold: float,
    markets: list[str] | None,
    price_type: str,
    no_trees: bool,
    climatology: str,
    seed: int,
):  # type: ignore[no-untyped-def]
    from shocktrace.experiments.config import ExperimentConfig

    return ExperimentConfig(
        name=name,
        country_iso3=country.upper(),
        commodity_codes=commodity,
        horizons=horizons,
        spike_threshold=threshold,
        market_codes=markets,
        price_types=[price_type],
        include_trees=not no_trees,
        climatology_mode=climatology,
        seed=seed,
    )


@app.command()
def features(
    country: str,
    commodity: Annotated[list[str], typer.Option()],
    horizons: list[int] = [1, 3],  # noqa: B006
    mode: ModeOpt = None,
) -> None:
    """Build and save the leakage-safe feature panel for a selection."""
    import uuid
    from datetime import UTC, datetime

    from shocktrace.db import models as m
    from shocktrace.db.session import session_scope
    from shocktrace.experiments.runner import select_series
    from shocktrace.features.builder import build_panel
    from shocktrace.services import load_datasets, store_for

    s = _settings(mode)
    cfg = _cfg("features", country, commodity, horizons, 0.10, None, "Retail", False, "expanding", 42)
    data, _ = load_datasets(store_for(s))
    ids, _ = select_series(data, cfg)
    if not ids:
        typer.echo("no eligible series for this selection")
        raise typer.Exit(1)
    fb = build_panel(data, ids, tuple(horizons))
    fid = f"fs_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    out = s.data_dir / "features" / s.shocktrace_mode.value / f"{fid}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    fb.panel.to_parquet(out, index=False)
    with session_scope(s.database_url) as ss:
        ss.add(
            m.FeatureSet(
                id=fid,
                mode=s.shocktrace_mode.value,
                path=str(out),
                n_rows=len(fb.panel),
                columns=list(fb.panel.columns),
                availability=fb.availability,
            )
        )
    typer.echo(f"{fid}: {len(fb.panel)} rows x {fb.panel.shape[1]} columns -> {out}")
    for w in fb.warnings:
        typer.echo(f"warning: {w}")


@app.command()
def backtest(
    country: Annotated[str, typer.Option()],
    commodity: Annotated[list[str], typer.Option()],
    name: str | None = None,
    horizon: Annotated[list[int] | None, typer.Option()] = None,
    threshold: float = 0.10,
    market: Annotated[list[str] | None, typer.Option()] = None,
    price_type: str = "Retail",
    no_trees: bool = False,
    climatology: str = "expanding",
    seed: int = 42,
    mode: ModeOpt = None,
) -> None:
    """Run a full experiment: walk-forward backtests, model comparisons, conclusion, forecasts."""
    from shocktrace.services import default_experiment_name, run_and_register

    s = _settings(mode)
    cfg = _cfg(
        name or default_experiment_name(s, country, commodity),
        country,
        commodity,
        horizon or [1, 3],
        threshold,
        market,
        price_type,
        no_trees,
        climatology,
        seed,
    )
    out = run_and_register(s, cfg)
    c = out.results["conclusion"]
    typer.echo(f"experiment {out.experiment_id}: {out.results['status']}")
    typer.echo(f"VERDICT: {c['verdict']} — {c['statement']}")
    for p in c["primary_comparisons"]:
        typer.echo(
            f"  {p['task']:14s} h={p['horizon']} {p['model_a']} vs {p['model_b']}: {p['verdict']} ({p['reason']})"
        )
    typer.echo(c["causal_disclaimer"])


@app.command()
def reproduce(experiment_id: str, mode: ModeOpt = None) -> None:
    """Re-run a saved experiment configuration on the current snapshots and compare results."""
    from shocktrace.services import load_saved_config, run_and_register

    s = _settings(mode)
    cfg = load_saved_config(s, experiment_id)
    old = json.loads((s.experiments_dir / experiment_id / "results.json").read_text())
    out = run_and_register(s, cfg, experiment_id=f"{experiment_id}_repro")
    same_data = all(
        old["manifest"]["snapshots"].get(k, {}).get("content_hash") == v.get("content_hash")
        for k, v in out.results["manifest"]["snapshots"].items()
    )
    typer.echo(f"original verdict: {old['conclusion']['verdict']} · reproduced: {out.results['conclusion']['verdict']}")
    typer.echo(f"identical input data: {same_data} · config hash {old['config_hash']} == {out.results['config_hash']}")
    diffs = []
    for t_old, t_new in zip(old["tasks"], out.results["tasks"], strict=False):
        for mname, met in t_old.get("models", {}).items():
            k = "mae" if t_old["task"] == "regression" else "brier"
            a, b = met.get(k), t_new.get("models", {}).get(mname, {}).get(k)
            if a is not None and b is not None and abs(a - b) > 1e-9:
                diffs.append(f"{t_old['task']} h{t_old['horizon']} {mname} {k}: {a:.6g} -> {b:.6g}")
    typer.echo("metrics identical" if not diffs else "metric differences:\n  " + "\n  ".join(diffs))


@app.command()
def forecast(experiment_id: str, mode: ModeOpt = None) -> None:
    """Show forward forecasts (issued or withheld, with validation status) for an experiment."""
    s = _settings(mode)
    res = json.loads((s.experiments_dir / experiment_id / "results.json").read_text())
    for f in res["forecasts"]:
        val = (
            f"p={f['probability']:.2f}"
            if "probability" in f
            else f"{f['point_price']:.2f} [{f['lower80']:.2f}, {f['upper80']:.2f}]"
            if "point_price" in f
            else ""
        )
        typer.echo(
            f"{f['status']:8s} {f['market_name'][:22]:22s} {f['task'][:5]} h={f['horizon']} "
            f"{f['origin_period']}→{f['target_period']} {val:28s} {f['validation_status']}"
        )


@app.command()
def report(experiment_id: str, output: Path | None = None, mode: ModeOpt = None) -> None:
    """Write a Markdown research report (and optional export bundle) for an experiment."""
    from shocktrace.reporting.report import export_bundle, markdown_report

    s = _settings(mode)
    d = s.experiments_dir / experiment_id
    md = markdown_report(json.loads((d / "results.json").read_text()))
    if output and output.suffix == ".zip":
        output.write_bytes(export_bundle(d))
    elif output:
        output.write_text(md)
    else:
        typer.echo(md)


if __name__ == "__main__":
    app()
