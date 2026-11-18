"""Market Almanac command-line interface."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from market_almanac import __version__
from market_almanac.config import RunMode, get_settings, reset_settings_cache
from market_almanac.logging import configure_logging

app = typer.Typer(help="Market Almanac: from environmental signals to economic risk.", no_args_is_help=True)


def _settings(mode: str | None = None):  # type: ignore[no-untyped-def]
    if mode:
        os.environ["MARKET_ALMANAC_MODE"] = mode
        reset_settings_cache()
    s = get_settings()
    configure_logging(s.log_level)
    return s


ModeOpt = Annotated[str | None, typer.Option("--mode", help="demo | live (overrides MARKET_ALMANAC_MODE)")]


def _echo_json(obj: object) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


@app.command()
def sources(mode: ModeOpt = None) -> None:
    """List data providers, their credentials state and licensing (no network calls)."""
    from market_almanac.providers import build_providers

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

    from market_almanac.db.session import get_engine

    s = _settings(mode)
    ok = True
    typer.echo(
        f"Market Almanac {__version__} · Python {platform.python_version()} · mode={s.market_almanac_mode.value}"
    )
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
    from market_almanac.providers import build_providers

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
        from market_almanac.services import check_health

        for r in asyncio.run(check_health(s)):
            color = "green" if r.status.value == "healthy" else "yellow"
            typer.secho(f"  {r.provider_id:12s} {r.status.value:15s} {r.latency_ms or '':>8} ms  {r.message}", fg=color)
    raise typer.Exit(0 if ok else 1)


@app.command("db-init")
def db_init(mode: ModeOpt = None) -> None:
    """Bring the database to the latest schema (Alembic migrations; safe to re-run)."""
    s = _settings(mode)
    from market_almanac.db.migrate import migrate

    rev = migrate(s.database_url)
    typer.echo(f"schema at revision {rev}")
    from market_almanac.services import sync_sources

    sync_sources(s)
    typer.echo(f"database ready: {s.redacted_database_url()}")


@app.command("demo-seed")
def demo_seed(skip_experiments: bool = False) -> None:
    """Generate SYNTHETIC demo data, quality report and demo experiments (no network)."""
    s = _settings("demo")
    from market_almanac.services import seed_demo

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
    from market_almanac.services import discover_candidates, ingest_prices, store_for

    if s.market_almanac_mode == RunMode.LIVE:
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
    from market_almanac import services as sv

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
    from market_almanac.services import run_quality

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
    from market_almanac.experiments.config import ExperimentConfig

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

    from market_almanac.db import models as m
    from market_almanac.db.session import session_scope
    from market_almanac.experiments.runner import select_series
    from market_almanac.features.builder import build_panel
    from market_almanac.services import load_datasets, store_for

    s = _settings(mode)
    cfg = _cfg("features", country, commodity, horizons, 0.10, None, "Retail", False, "expanding", 42)
    data, _ = load_datasets(store_for(s))
    ids, _ = select_series(data, cfg)
    if not ids:
        typer.echo("no eligible series for this selection")
        raise typer.Exit(1)
    fb = build_panel(data, ids, tuple(horizons))
    fid = f"fs_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    out = s.data_dir / "features" / s.market_almanac_mode.value / f"{fid}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    fb.panel.to_parquet(out, index=False)
    with session_scope(s.database_url) as ss:
        ss.add(
            m.FeatureSet(
                id=fid,
                mode=s.market_almanac_mode.value,
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
    from market_almanac.services import default_experiment_name, run_and_register

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
    """Re-run a saved experiment on the snapshots recorded in its manifest and compare results.

    Differences in metrics are expected when the stored run predates a method revision; the
    command prints both revisions so the cause is visible.
    """
    from market_almanac.services import load_saved_config, run_and_register

    s = _settings(mode)
    cfg = load_saved_config(s, experiment_id)
    old = json.loads((s.experiments_dir / experiment_id / "results.json").read_text())
    out = run_and_register(
        s, cfg, experiment_id=f"{experiment_id}_repro"[:64], pinned_snapshots=old["manifest"].get("snapshots") or None
    )
    typer.echo(
        f"method revision: {old['manifest'].get('method_revision')!r} -> {out.results['manifest']['method_revision']!r}"
    )
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
    from market_almanac.reporting.report import export_bundle, markdown_report

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


@app.command()
def study(
    phase: Annotated[str, typer.Option(help="exploratory | confirmatory | all")] = "exploratory",
    variant: Annotated[list[str] | None, typer.Option(help="limit to these variants (default: all)")] = None,
    mode: ModeOpt = None,
) -> None:
    """Run the pre-specified production-region weather study (docs/research/RESEARCH_PROTOCOL.md)."""
    from market_almanac.research.report import render_markdown
    from market_almanac.research.study import STUDY, VARIANTS, run_study

    s = _settings(mode or "live")
    res = run_study(
        s, phase, STUDY, tuple(variant) if variant else VARIANTS, progress=lambda m: typer.echo(f"  run {m}")
    )
    out = s.experiments_dir / "studies" / STUDY.study_id / f"tables_{phase}.md"
    out.write_text(render_markdown(res))
    typer.echo(f"wrote {out}")
    conf = res["confirmatory"]
    if conf["n_tests"]:
        typer.echo(f"confirmatory outcome: {conf['outcome']['label']} - {conf['outcome']['statement']}")


@app.command()
def supersede(
    old_id: str,
    new_id: str,
    reason: Annotated[str, typer.Option(help="why the old run no longer represents the current method")],
    mode: ModeOpt = None,
) -> None:
    """Mark an experiment as superseded by a newer run (history is kept; listings default to current)."""
    from market_almanac.db import repository as repo
    from market_almanac.db.session import session_scope

    s = _settings(mode)
    with session_scope(s.database_url) as db:
        e = repo.supersede_experiment(db, old_id, new_id, reason)
        typer.echo(f"{e.id} superseded by {e.superseded_by}")


@app.command()
def materialize(mode: ModeOpt = None) -> None:
    """Build the public series catalog and coverage inventory from the current snapshots."""
    from market_almanac.services import materialize_public

    _echo_json(materialize_public(_settings(mode)))


@app.command("sync-db")
def sync_db(mode: ModeOpt = None) -> None:
    """Rebuild the database index (snapshots, markets, experiments, lineage) from stored artefacts."""
    from market_almanac.services import sync_database

    s = _settings(mode)
    res = sync_database(s)
    typer.echo(f"database: {s.redacted_database_url()}")
    typer.echo(f"snapshots registered: {res['snapshots']} | experiments registered: {len(res['experiments'])}")
    typer.echo(f"superseded: {len(res['superseded'])} | lineage entries skipped: {len(res['lineage_skipped'])}")


@app.command("bundle-export")
def bundle_export(
    mode: ModeOpt = None,
    out: Annotated[Path, typer.Option(help="output directory")] = Path("dist"),
) -> None:
    """Package lake snapshots, the public catalog and experiment results into a verified data bundle."""
    from market_almanac.data.public_bundle import build_bundle

    s = _settings(mode)
    _echo_json(build_bundle(s.data_dir, s.market_almanac_mode.value, out))


@app.command("bundle-install")
def bundle_install(
    source: Annotated[str, typer.Argument(help="local path or https:// URL of a .tar.gz data bundle")],
    sha256: Annotated[str | None, typer.Option(help="expected SHA-256 of the archive")] = None,
    mode: ModeOpt = None,
) -> None:
    """Verify and install a data bundle into DATA_DIR (never overwrites differing files). Run sync-db after."""
    from market_almanac.data.public_bundle import install_bundle

    s = _settings(mode)
    _echo_json(install_bundle(source, s.data_dir, sha256))


global_app = typer.Typer(
    help="Global discovery, partitioned ingestion and the coverage registry.", no_args_is_help=True
)
app.add_typer(global_app, name="global")


@global_app.command("discover")
def global_discover(mode: ModeOpt = None) -> None:
    """Record which countries HDX HAPI reports WFP price coverage for (metadata only)."""
    from market_almanac.globaldata import global_dir
    from market_almanac.globaldata.discovery import discover_hdx, save_discovery

    s = _settings(mode)
    rec = asyncio.run(discover_hdx(s))
    p = save_discovery(global_dir(s), rec)
    typer.echo(f"{len(rec['countries'])} countries with WFP price availability; saved {p}")


@global_app.command("ingest")
def global_ingest(
    countries: Annotated[str | None, typer.Option(help="comma-separated ISO3 codes (default: all discovered)")] = None,
    resume: Annotated[str | None, typer.Option(help="run id to resume")] = None,
    exclude: Annotated[str | None, typer.Option(help="comma-separated ISO3 codes to skip")] = None,
    concurrency: Annotated[int, typer.Option(help="countries fetched at once (max 3)")] = 2,
    mode: ModeOpt = None,
) -> None:
    """Fetch WFP prices into per-country immutable snapshots; resumable and idempotent."""
    from market_almanac.globaldata import global_dir
    from market_almanac.globaldata.discovery import latest_discovery
    from market_almanac.globaldata.ingest import RunLog, execute_run, hdx_price_fetcher, new_run
    from market_almanac.globaldata.partitions import PartitionStore

    s = _settings(mode)
    if s.market_almanac_mode != RunMode.LIVE:
        raise typer.BadParameter("global ingestion requires --mode live")
    gdir = global_dir(s)
    runlog = RunLog(gdir)
    if resume:
        state = runlog.load(resume)
    else:
        if countries:
            codes = [c.strip().upper() for c in countries.split(",") if c.strip()]
        else:
            disc = latest_discovery(gdir)
            if disc is None:
                raise typer.BadParameter("no discovery record; run `market-almanac global discover` first")
            codes = sorted(disc["countries"])
        skip = {c.strip().upper() for c in (exclude or "").split(",") if c.strip()}
        state = new_run([c for c in codes if c not in skip], source="hdx_hapi food-prices-market-monitor")
    typer.echo(f"run {state.run_id}: {len(state.countries)} countries")
    store = PartitionStore(s.lake_dir, s.market_almanac_mode.value)
    state = asyncio.run(execute_run(state, store, runlog, hdx_price_fetcher(s), concurrency=concurrency))
    typer.echo(json.dumps(state.summary()))
    failed = {k: v.error for k, v in state.countries.items() if v.status == "failed"}
    if failed:
        typer.echo("failed: " + json.dumps(failed, indent=1))


@global_app.command("status")
def global_status(run_id: Annotated[str | None, typer.Argument()] = None, mode: ModeOpt = None) -> None:
    """Show a run's per-country outcomes (latest run when no id is given)."""
    from market_almanac.globaldata import global_dir
    from market_almanac.globaldata.ingest import RunLog

    runlog = RunLog(global_dir(_settings(mode)))
    ids = runlog.list()
    if not ids:
        typer.echo("no runs recorded")
        raise typer.Exit(1)
    st = runlog.load(run_id or ids[-1])
    typer.echo(f"{st.run_id}: {json.dumps(st.summary())}")
    for c in st.countries.values():
        typer.echo(f"  {c.country_iso3} {c.status:9} rows={c.rows} attempts={c.attempts} {c.error or ''}")


@global_app.command("registry")
def global_registry(
    package: Annotated[bool, typer.Option(help="also write the copy shipped with the code (for deployment)")] = False,
    mode: ModeOpt = None,
) -> None:
    """Build the coverage registry from discovery, stored partitions, run logs and evaluations."""
    from market_almanac.globaldata.registry import (
        PACKAGED_REGISTRY,
        build_registry,
        collect_inputs,
        registry_path,
        write_registry,
    )

    s = _settings(mode)
    reg = build_registry(**collect_inputs(s))
    p = write_registry(reg, registry_path(s))
    typer.echo(f"wrote {p}")
    if package:
        write_registry(reg, PACKAGED_REGISTRY)
        typer.echo(f"wrote {PACKAGED_REGISTRY}")
    _echo_json({"counts": reg["counts"], "totals": reg["totals"]})


@global_app.command("weather")
def global_weather(
    spec_path: Annotated[Path, typer.Option("--spec", help="research specification whose markets need weather")],
    concurrency: Annotated[int, typer.Option(help="countries at once (each fetches its cells in parallel)")] = 1,
    resume: Annotated[str | None, typer.Option(help="run id to resume")] = None,
    mode: ModeOpt = None,
) -> None:
    """Fetch NASA POWER weather for the market cells of a specification's eligible groups (resumable)."""
    from market_almanac.globaldata import global_dir
    from market_almanac.globaldata.ingest import RunLog, execute_run, new_run
    from market_almanac.globaldata.partitions import PartitionStore
    from market_almanac.globaldata.weather import cells_for_markets, power_fetcher
    from market_almanac.workbench.data import GROUP_KEYS, eligibility_table, load_prices, select_groups
    from market_almanac.workbench.spec import load_spec

    s = _settings(mode)
    spec = load_spec(spec_path)
    countries = [c for c in spec.population.countries if c not in spec.population.exclude_countries]
    pop = load_prices(s, countries)
    elig = eligibility_table(pop.prices, spec)
    groups = select_groups(elig, spec)
    ok = elig[elig["eligible"]].merge(groups[GROUP_KEYS], on=GROUP_KEYS)
    mk = pop.prices[pop.prices["series_id"].isin(ok["series_id"])].drop_duplicates(["country_iso3", "market_code"])
    wanted = {c: cells_for_markets(g) for c, g in mk.groupby("country_iso3")}
    typer.echo(f"{sum(len(v) for v in wanted.values())} grid cells in {len(wanted)} countries")
    runlog = RunLog(global_dir(s))
    state = (
        runlog.load(resume)
        if resume
        else new_run(sorted(wanted), dataset="weather_monthly", provider="nasa_power", spec=spec.id)
    )
    store = PartitionStore(s.lake_dir, s.market_almanac_mode.value)
    state = asyncio.run(execute_run(state, store, runlog, power_fetcher(s, wanted), concurrency=concurrency, qc=False))
    typer.echo(f"{state.run_id}: {json.dumps(state.summary())}")


research_app = typer.Typer(
    help="Research workbench: validate, preview, freeze, run, verify, export.", no_args_is_help=True
)
app.add_typer(research_app, name="research")
SpecArg = Annotated[Path, typer.Argument(help="research specification (YAML or JSON)")]


def _load_spec_or_exit(path: Path):  # type: ignore[no-untyped-def]
    from market_almanac.workbench.spec import SpecError, load_spec

    try:
        return load_spec(path)
    except SpecError as exc:
        typer.echo(f"invalid specification {path}:\n{exc}", err=True)
        raise typer.Exit(2) from exc


@research_app.command("validate")
def research_validate(spec_path: SpecArg) -> None:
    """Check a specification for errors and scientific contradictions (no data access)."""
    from market_almanac.workbench.spec import spec_summary

    _echo_json({"valid": True, **spec_summary(_load_spec_or_exit(spec_path))})


@research_app.command("preview")
def research_preview(spec_path: SpecArg, mode: ModeOpt = None) -> None:
    """Show the population a specification selects (metadata only; nothing is estimated)."""
    from market_almanac.workbench.data import preview

    pv = preview(_settings(mode), _load_spec_or_exit(spec_path))
    groups = pv.pop("groups")
    _echo_json({k: v for k, v in pv.items() if k != "snapshots"})
    for g in groups[:60]:
        typer.echo(
            f"  {g['country_iso3']} {g['commodity_name'][:40]:40} {g['unit']:>8} {g['price_type']:9} "
            f"{g['eligible_series']:4} eligible"
        )


@research_app.command("freeze")
def research_freeze(spec_path: SpecArg, mode: ModeOpt = None) -> None:
    """Freeze a specification: hash, git revision, data snapshots and analysis groups, before any estimation."""
    import subprocess

    from market_almanac.workbench.execute import freeze

    spec = _load_spec_or_exit(spec_path)
    if spec.evidence_class == "confirmatory":
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(spec_path)], capture_output=True)
        if tracked.returncode != 0:
            typer.echo("a confirmatory specification must be committed to git before it is frozen", err=True)
            raise typer.Exit(2)
    rec = freeze(_settings(mode), spec)
    typer.echo(
        f"frozen {rec['spec_id']} hash={rec['spec_hash'][:16]} groups={len(rec['groups'])} "
        f"commit={rec['code'].get('git_commit')}"
    )


@research_app.command("run")
def research_run(
    spec_path: SpecArg,
    workers: Annotated[int, typer.Option(help="parallel experiment processes")] = 4,
    mode: ModeOpt = None,
) -> None:
    """Execute a specification (confirmatory specifications must be frozen); resumable."""
    from market_almanac.workbench.execute import FreezeError, execute

    try:
        res = execute(_settings(mode), _load_spec_or_exit(spec_path), workers=workers)
    except FreezeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    for h in res.get("hypotheses", []):
        r = h["result"]
        typer.echo(
            f"{h['hypothesis']['id']}: ratio={r.get('loss_ratio')} p_adj={h.get('p_adjusted')} "
            f"-> {h['evidence']['class']}"
        )
    typer.echo(json.dumps(res.get("execution", {}), default=str))


@research_app.command("verify")
def research_verify(package_dir: Annotated[Path, typer.Argument()]) -> None:
    """Recompute every checksum of a research package."""
    from market_almanac.workbench.package import verify_package

    out = verify_package(package_dir)
    _echo_json(out)
    if not out["ok"]:
        raise typer.Exit(1)


@research_app.command("export")
def research_export(
    spec_id: Annotated[str, typer.Argument()],
    out: Annotated[Path, typer.Option(help="output .tar.gz")] = Path("dist/study.tar.gz"),
    mode: ModeOpt = None,
) -> None:
    """Export a study directory (results, predictions, RO-Crate metadata, checksums) as a tarball."""
    from market_almanac.workbench.execute import studies_dir
    from market_almanac.workbench.package import export_package

    s = _settings(mode)
    root = studies_dir(s) / spec_id
    if not (root / "SHA256SUMS").exists():
        raise typer.BadParameter(f"no packaged study {spec_id}")
    typer.echo(str(export_package(root, out)))
