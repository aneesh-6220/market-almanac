"""Freeze, execute and package research specifications.

``freeze`` records the specification hash, the git revision, the data snapshots and the
analysis groups (selected from metadata only) *before* anything is estimated. ``execute`` refuses
a confirmatory specification that is not frozen or whose text changed since freezing, re-reads
exactly the frozen snapshots, runs the existing audited experiment engine per group, and pools
the stored predictions with ``workbench.pooled``. Groups already completed with the same
configuration are skipped, so an interrupted study resumes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import market_almanac
from market_almanac.data.store import DatasetStore
from market_almanac.experiments.config import ExperimentConfig
from market_almanac.experiments.runner import code_provenance, run_experiment, save_experiment
from market_almanac.globaldata.partitions import PartitionStore
from market_almanac.workbench import pooled
from market_almanac.workbench.data import eligibility_table, load_prices, preview, select_groups
from market_almanac.workbench.regions import macro_region, subregion
from market_almanac.workbench.spec import ResearchSpec

STUDY_ENGINE_VERSION = "workbench-1"


class FreezeError(RuntimeError):
    pass


def studies_dir(settings: Any) -> Path:
    return Path(settings.data_dir) / "studies" / settings.market_almanac_mode.value


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)


def group_id(g: dict[str, Any]) -> str:
    unit = re.sub(r"[^A-Za-z0-9]+", "", str(g["unit"]))[:12] or "u"
    pt = str(g["price_type"])[:1].upper()
    return f"{g['country_iso3']}_{g['commodity_code']}_{unit}_{pt}_{g['currency']}"


# --------------------------------------------------------------------------------------- freeze


def freeze(settings: Any, spec: ResearchSpec, *, require_clean_git: bool | None = None) -> dict[str, Any]:
    """Record the specification, code revision, data snapshots and analysis groups; immutable."""
    code = code_provenance()
    clean_needed = spec.evidence_class == "confirmatory" if require_clean_git is None else require_clean_git
    if clean_needed and (code.get("dirty") is not False or not code.get("git_commit")):
        raise FreezeError("a confirmatory specification must be frozen from a committed, clean git tree")
    pv = preview(settings, spec)
    weather_snaps: dict[str, Any] = {}
    if spec.study_type == "predictive" and pv["groups"]:
        pop = load_prices(settings, sorted({g["country_iso3"] for g in pv["groups"]}))
        mk = pop.prices.dropna(subset=["lat", "lon"]).drop_duplicates(["country_iso3", "market_code"])
        from market_almanac.data.identity import weather_location_id

        locs = {weather_location_id(a, b) for a, b in zip(mk["lat"], mk["lon"], strict=True) if not (a == 0 and b == 0)}
        _, weather_snaps = load_weather(settings, sorted({g["country_iso3"] for g in pv["groups"]}), locs)
    record = {
        "freeze_version": "ma-freeze/1",
        "spec_id": spec.id,
        "spec_hash": spec.spec_hash(),
        "spec": spec.model_dump(mode="json"),
        "frozen_at": datetime.now(UTC).isoformat(),
        "code": code,
        "software_version": market_almanac.__version__,
        "data_snapshots": {**pv["snapshots"], **weather_snaps},
        "groups": pv["groups"],
        "selection_hash": hashlib.sha256(json.dumps(pv["groups"], sort_keys=True, default=str).encode()).hexdigest(),
        "population_summary": {k: v for k, v in pv.items() if k not in ("groups", "snapshots")},
        "outcomes_inspected_before_freeze": False,
        "statement": (
            "Groups were selected from observation metadata (counts, coverage, gaps, coordinates) without "
            "estimating any model on this population."
        ),
    }
    p = studies_dir(settings) / spec.id / "freeze.json"
    if p.exists():
        old = json.loads(p.read_text())
        if old["spec_hash"] != record["spec_hash"]:
            raise FreezeError(
                f"{spec.id} is already frozen with a different specification (hash {old['spec_hash'][:12]}); "
                "a changed design needs a new study id"
            )
        return old
    _atomic_json(p, record)
    return record


def load_freeze(settings: Any, spec_id: str) -> dict[str, Any] | None:
    p = studies_dir(settings) / spec_id / "freeze.json"
    return json.loads(p.read_text()) if p.exists() else None


# --------------------------------------------------------------------------------------- inputs


def load_weather(
    settings: Any, countries: list[str], location_ids: set[str], pinned: dict[str, dict[str, Any]] | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Weather for the given cells: country partitions first, then the original research lake.

    With ``pinned`` (a freeze record's snapshots) exactly those snapshots are read and verified.
    """
    mode = settings.market_almanac_mode.value
    ps = PartitionStore(settings.lake_dir, mode)
    frames, snaps = [], {}
    for c in countries:
        want = (pinned or {}).get(f"weather_monthly:{c}")
        m = ps.get("weather_monthly", c, want["snapshot_id"]) if want else ps.latest("weather_monthly", c)
        if m:
            df = ps.read("weather_monthly", c, m.snapshot_id, verify=bool(want))
            frames.append(df[df["location_id"].isin(location_ids)])
            snaps[f"weather_monthly:{c}"] = {
                "layout": "partition",
                "snapshot_id": m.snapshot_id,
                "observation_hash": m.observation_hash,
                "file_sha256": m.file_sha256,
            }
    lake = DatasetStore(settings.lake_dir, mode)
    latest = lake.latest("weather_monthly")
    want_lake = (pinned or {}).get("weather_monthly:lake")
    if want_lake:
        latest = next(
            (x for x in lake.list_snapshots("weather_monthly") if x.snapshot_id == want_lake["snapshot_id"]), None
        )
        if latest is None:
            raise FileNotFoundError(f"pinned weather snapshot {want_lake['snapshot_id']} is not in this lake")
    if latest:
        have = set(pd.concat(frames)["location_id"].unique()) if frames else set()
        need = list(location_ids - have)
        if need:
            df = pd.read_parquet(
                lake.path("weather_monthly", latest.snapshot_id), filters=[("location_id", "in", need)]
            )
            if len(df):
                frames.append(df)
                snaps["weather_monthly:lake"] = {
                    "layout": "lake",
                    "snapshot_id": latest.snapshot_id,
                    "content_hash": latest.content_hash,
                }
    w = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(w):
        w = w.drop_duplicates(["location_id", "period"], keep="first")
    return w, snaps


def shift_weather(w: pd.DataFrame, months: int) -> pd.DataFrame:
    """Negative control: each month receives the weather observed ``months`` earlier (no leakage)."""
    out = w.copy()
    out["period"] = out["period"] + pd.DateOffset(months=months)
    return out


def permute_cells(w: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Negative control: every grid cell's series is relabelled as a different, distant cell."""
    ids = sorted(w["location_id"].unique())
    if len(ids) < 2:
        return w
    lat = {i: float(i.split("_")[1]) for i in ids}
    order = sorted(ids, key=lambda i: (lat[i], i))
    k = len(order) // 2  # pair each cell with one half the latitude ranking away
    mapping = {order[j]: order[(j + k) % len(order)] for j in range(len(order))}
    out = w.copy()
    out["location_id"] = out["location_id"].map(mapping)
    return out


VARIANTS: dict[str, dict[str, Any]] = {
    "primary": {},
    "price_lag_0": {"price_release_lag_months": 0},
    "price_lag_2": {"price_release_lag_months": 2},
    "weather_lag_1": {"weather_release_lag_months": 1},
    "raw_precipitation": {"use_precip_qc": False},
    "weather_time_shift_60": {"weather_transform": "shift60"},
    "weather_permuted_cells": {"weather_transform": "permute"},
}
POOLED_ONLY = ("leave_one_country_out", "drop_top3_months")  # computed from the primary predictions


def _config(spec: ResearchSpec, g: dict[str, Any], variant: str) -> ExperimentConfig:
    pr = spec.predictive
    assert pr is not None
    over = {k: v for k, v in VARIANTS[variant].items() if k != "weather_transform"}
    return ExperimentConfig(
        name=f"{spec.id}: {g['country_iso3']} {g['commodity_name']} ({g['unit']}, {g['price_type']})"[:120],
        country_iso3=g["country_iso3"],
        commodity_codes=[str(g["commodity_code"])],
        price_types=[g["price_type"]],
        units=[g["unit"]],
        horizons=pr.horizons,
        families=pr.families,
        include_trees=pr.include_tree_models,
        primary_regression_model=f"ridge_{max(pr.families)}",
        primary_classification_model=f"logit_{max(pr.families)}",
        price_release_lag_months=over.get("price_release_lag_months", spec.timing.price_release_lag_months),
        weather_release_lag_months=over.get("weather_release_lag_months", spec.timing.weather_release_lag_months),
        use_precip_qc=over.get("use_precip_qc", True),
        evidence_class=spec.evidence_class,
        study=spec.id[:80],
        variant=variant[:32],
        min_train_months=pr.min_train_months,
        refit_every=pr.refit_every,
        min_series_observations=spec.population.min_observations,
        min_test_periods=max(12, min(pr.min_test_periods, 24)),
        seed=spec.seed,
    )


def _run_group(args: tuple[dict[str, Any], dict[str, pd.DataFrame], str, str, str]) -> dict[str, Any]:
    cfg_json, datasets, exp_id, out_dir, mode = args
    cfg = ExperimentConfig.model_validate(cfg_json)
    snaps = datasets.pop("_snapshots", None)
    t0 = time.perf_counter()
    out = run_experiment(datasets, cfg, mode=mode, snapshots=snaps, experiment_id=exp_id)  # type: ignore[arg-type]
    d = save_experiment(out, Path(out_dir))
    return {
        "experiment_id": exp_id,
        "dir": str(d),
        "status": out.results.get("status"),
        "seconds": time.perf_counter() - t0,
    }


# --------------------------------------------------------------------------------------- execute


def execute(
    settings: Any, spec: ResearchSpec, *, workers: int = 4, variants: list[str] | None = None
) -> dict[str, Any]:
    if spec.study_type != "predictive":
        from market_almanac.workbench.other_modes import execute_other

        return execute_other(settings, spec)
    fr = load_freeze(settings, spec.id)
    if spec.evidence_class == "confirmatory":
        if fr is None:
            raise FreezeError("confirmatory study: freeze the specification first (market-almanac research freeze)")
        if fr["spec_hash"] != spec.spec_hash():
            raise FreezeError("the specification changed after it was frozen; a changed design needs a new study id")
    started = datetime.now(UTC)
    root = studies_dir(settings) / spec.id
    exp_dir = root / "experiments"
    if fr is not None:
        groups = fr["groups"]
        pop = load_prices(settings, sorted({g["country_iso3"] for g in groups}), pinned=fr["data_snapshots"])
    else:
        countries = [c for c in spec.population.countries if c not in spec.population.exclude_countries]
        pop = load_prices(settings, countries)
        groups = select_groups(eligibility_table(pop.prices, spec), spec).to_dict(orient="records")
    prices = pop.prices
    markets = prices.dropna(subset=["lat", "lon"]).drop_duplicates(["country_iso3", "market_code"])
    from market_almanac.data.identity import weather_location_id

    locs = {
        weather_location_id(a, b)
        for a, b in zip(markets["lat"], markets["lon"], strict=True)
        if not (a == 0 and b == 0)
    }
    weather, wsnaps = load_weather(
        settings, sorted({g["country_iso3"] for g in groups}), locs, pinned=fr["data_snapshots"] if fr else None
    )
    snapshots = {**pop.snapshots, **wsnaps}

    wanted = ["primary", *[v for v in spec.robustness + spec.negative_controls if v in VARIANTS]]
    wanted = [v for v in wanted if variants is None or v in variants]
    jobs = []
    for g in groups:
        gid = group_id(g)
        gp = prices[
            (prices["country_iso3"] == g["country_iso3"])
            & (prices["commodity_code"].astype(str) == str(g["commodity_code"]))
            & (prices["currency"] == g["currency"])
        ]
        gm = gp.dropna(subset=["lat", "lon"]).drop_duplicates("market_code")
        glocs = {
            weather_location_id(a, b) for a, b in zip(gm["lat"], gm["lon"], strict=True) if not (a == 0 and b == 0)
        }
        for v in wanted:
            cfg = _config(spec, g, v)
            exp_id = f"{spec.id}__{gid}__{v}"
            done = exp_dir / exp_id / "results.json"
            if done.exists() and json.loads(done.read_text()).get("config_hash") == cfg.config_hash():
                continue
            tr = VARIANTS[v].get("weather_transform")
            w = (
                weather
                if tr is None
                else shift_weather(weather, 60)
                if tr == "shift60"
                else permute_cells(weather, spec.seed)
            )
            w = w[w["location_id"].isin(glocs)] if len(w) else w  # only this group's cells travel to the worker
            ds = {
                "prices": gp,
                "weather_monthly": w,
                "macro": pd.DataFrame(),
                "agriculture": pd.DataFrame(),
                "_snapshots": snapshots,
            }
            if any(f in spec.predictive.families for f in ("C", "D")):  # type: ignore[union-attr]
                lake = DatasetStore(settings.lake_dir, settings.market_almanac_mode.value)
                ds["macro"], ds["agriculture"] = lake.read("macro"), lake.read("agriculture")
            jobs.append((cfg.model_dump(), ds, exp_id, str(exp_dir), settings.market_almanac_mode.value))
    log: list[dict[str, Any]] = []
    if jobs:
        with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = [pool.submit(_run_group, j) for j in jobs]
            for f in as_completed(futs):
                try:
                    log.append(f.result())
                except Exception as exc:  # one failing group is recorded, the study continues
                    log.append({"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
    results = analyse(settings, spec, groups, snapshots, fr)
    results["execution"] = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "jobs_run": len(jobs),
        "jobs_failed": sum(1 for x in log if x.get("status") == "failed"),
        "failures": [x for x in log if x.get("status") == "failed"][:20],
        "workers": workers,
    }
    _atomic_json(root / "results.json", results)
    from market_almanac.workbench.package import write_package

    write_package(settings, spec, root)
    return results


def _collect_predictions(root: Path, spec: ResearchSpec, groups: list[dict[str, Any]], variant: str) -> pd.DataFrame:
    frames = []
    for g in groups:
        p = root / "experiments" / f"{spec.id}__{group_id(g)}__{variant}" / "predictions.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df = df[df["task"] == "regression"]
        df["country_iso3"] = g["country_iso3"]
        df["group_id"] = group_id(g)
        df["commodity_category"] = g.get("commodity_category")
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _test_start(spec: ResearchSpec) -> pd.Timestamp | None:
    pr = spec.predictive
    return pd.Timestamp(pr.test_start) if pr and pr.test_start else None


def analyse(
    settings: Any,
    spec: ResearchSpec,
    groups: list[dict[str, Any]],
    snapshots: dict[str, Any],
    fr: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pooled hypothesis tests, robustness, negative controls, heterogeneity and baseline skill."""
    pr = spec.predictive
    assert pr is not None
    root = studies_dir(settings) / spec.id
    inf = spec.inference
    ts = _test_start(spec)
    # commodity categories from the stored prices (metadata), for heterogeneity summaries
    cats = _categories(root, spec, groups)
    for g in groups:
        g["commodity_category"] = cats.get(group_id(g))
    primary = _collect_predictions(root, spec, groups, "primary")
    if len(primary):
        primary.to_parquet(root / "predictions_primary.parquet", index=False)

    def cmp(preds: pd.DataFrame, a: str, b: str, h: int, how: str | None = None) -> dict[str, Any]:
        rows = pooled.matched_losses(preds, a, b, h, ts)
        return pooled.compare(
            rows,
            h,
            how=how or pr.loss_aggregation,
            bootstrap=inf.bootstrap if inf.bootstrap != "none" else "none",
            reps=inf.bootstrap_reps,
            seed=spec.seed,
            alpha=inf.alpha,
            min_periods=pr.min_test_periods,
        )

    hyp: list[dict[str, Any]] = []
    for h in pr.hypotheses:
        r = (
            cmp(primary, f"ridge_{h.baseline}", f"ridge_{h.challenger}", h.horizon)
            if len(primary)
            else {"status": "insufficient_data"}
        )
        p = r.get("p_challenger_better") if h.alternative == "challenger_better" else r.get("p_two_sided")
        hyp.append({"hypothesis": h.model_dump(), "result": r, "p_raw": p})
    adj = pooled.adjust([x["p_raw"] for x in hyp], inf.multiplicity)
    for x, pa in zip(hyp, adj, strict=True):
        x["p_adjusted"] = pa
        x["evidence"] = pooled.evidence(x["result"], pa, inf.alpha, x["hypothesis"]["alternative"])

    # robustness and negative controls: the same contrasts, re-estimated under each variant
    def contrasts() -> list[tuple[str, str, int]]:
        return [(f"ridge_{h.baseline}", f"ridge_{h.challenger}", h.horizon) for h in pr.hypotheses]

    variants_out = []
    for v in [x for x in spec.robustness + spec.negative_controls if x in VARIANTS]:
        pv = _collect_predictions(root, spec, groups, v)
        for a, b, hz in contrasts():
            r = cmp(pv, a, b, hz) if len(pv) else {"status": "insufficient_data"}
            variants_out.append(
                {
                    "variant": v,
                    "kind": "negative_control" if v in spec.negative_controls else "robustness",
                    "contrast": f"{b} vs {a}",
                    "horizon": hz,
                    **{
                        k: r.get(k)
                        for k in (
                            "status",
                            "loss_ratio",
                            "p_challenger_better",
                            "p_two_sided",
                            "n_months",
                            "n_countries",
                            "n_series",
                        )
                    },
                    "ci_primary": r.get("ci_primary"),
                }
            )

    # baseline skill: is the price-history model better than no-change and seasonal-naive forecasts?
    skill = []
    for hz in pr.horizons:
        for base in ("naive", "seasonal_naive"):
            r = cmp(primary, base, "ridge_A", hz) if len(primary) else {"status": "insufficient_data"}
            skill.append(
                {
                    "baseline": base,
                    "model": "ridge_A",
                    "horizon": hz,
                    **{
                        k: r.get(k)
                        for k in (
                            "status",
                            "loss_ratio",
                            "p_challenger_better",
                            "p_challenger_worse",
                            "n_months",
                            "n_countries",
                            "n_series",
                        )
                    },
                    "ci_primary": r.get("ci_primary"),
                }
            )

    hetero = _heterogeneity(primary, spec, groups, ts) if len(primary) else []
    countries_tbl = _country_table(primary, spec, ts) if len(primary) else []
    return {
        "study_engine": STUDY_ENGINE_VERSION,
        "spec_id": spec.id,
        "spec_hash": spec.spec_hash(),
        "title": spec.title,
        "question": spec.question,
        "estimand": spec.estimand,
        "evidence_class": spec.evidence_class,
        "frozen": fr is not None,
        "frozen_at": fr["frozen_at"] if fr else None,
        "freeze_code": fr["code"] if fr else None,
        "selection_hash": fr["selection_hash"] if fr else None,
        "test_start": ts.date().isoformat() if ts is not None else None,
        "groups": groups,
        "n_groups": len(groups),
        "n_countries": len({g["country_iso3"] for g in groups}),
        "data_snapshots": snapshots,
        "hypotheses": hyp,
        "multiplicity": {"method": inf.multiplicity, "family": [h.id for h in pr.hypotheses], "alpha": inf.alpha},
        "variants": variants_out,
        "baseline_skill": skill,
        "heterogeneity": hetero,
        "countries": countries_tbl,
        "inference_note": inf.unit_of_inference,
        "timing": spec.timing.model_dump(),
        "limitations": [*spec.limitations, spec.timing.vintage_statement],
        "code": code_provenance(),
        "software_version": market_almanac.__version__,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _categories(root: Path, spec: ResearchSpec, groups: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for g in groups:
        p = root / "experiments" / f"{spec.id}__{group_id(g)}__primary" / "results.json"
        cat = None
        if p.exists():
            q = json.loads(p.read_text()).get("series_quality") or []
            cat = None if not q else q[0].get("commodity_category")
        out[group_id(g)] = cat or g.get("commodity_category")
    return out


def _heterogeneity(
    primary: pd.DataFrame, spec: ResearchSpec, groups: list[dict[str, Any]], ts: pd.Timestamp | None
) -> list[dict[str, Any]]:
    """Exploratory subgroup comparisons (pre-specified dimensions; Benjamini-Hochberg within the family)."""
    pr = spec.predictive
    assert pr is not None
    gmeta = pd.DataFrame(groups)
    gmeta["group_id"] = [group_id(g) for g in groups]
    p = primary.copy()
    p["macro_region"] = p["country_iso3"].map(macro_region)
    p["subregion"] = p["country_iso3"].map(subregion)
    names = gmeta.set_index("group_id")["commodity_name"].astype(str).str.lower()
    imported = names.str.contains("import")
    p["origin_label"] = p["group_id"].map(imported).map({True: "labelled imported", False: "not labelled imported"})
    # pre-test volatility of each series (training-period information only)
    vol = _pretest_volatility(p, ts)
    p["volatility_tercile"] = p["series_id"].map(vol)
    out: list[dict[str, Any]] = []
    for h in pr.hypotheses:
        a, b = f"ridge_{h.baseline}", f"ridge_{h.challenger}"
        for dim in ("macro_region", "origin_label", "volatility_tercile"):
            for level, sub in p.groupby(dim):
                rows = pooled.matched_losses(sub, a, b, h.horizon, ts)
                r = pooled.compare(
                    rows,
                    h.horizon,
                    how=pr.loss_aggregation,
                    bootstrap="none",
                    reps=200,
                    seed=spec.seed,
                    min_periods=pr.min_test_periods,
                )
                out.append(
                    {
                        "hypothesis": h.id,
                        "dimension": dim,
                        "level": str(level),
                        **{
                            k: r.get(k)
                            for k in ("status", "loss_ratio", "p_two_sided", "n_months", "n_countries", "n_series")
                        },
                        "ci_block": r.get("ci_block"),
                    }
                )
    adj = pooled.adjust([x.get("p_two_sided") for x in out], "benjamini_hochberg")
    for x, q in zip(out, adj, strict=True):
        x["q_value_bh"] = q
        x["evidence_class"] = "exploratory"
    return out


def _pretest_volatility(p: pd.DataFrame, ts: pd.Timestamp | None) -> dict[str, str]:
    """Tercile of each series' sd of realised 1-month log changes before the test period."""
    base = p[(p["model"] == "naive") & (p["horizon"] == min(p["horizon"]))]
    if ts is not None:
        pre = base[base["origin"] < ts]
        base = pre if len(pre) else base.groupby("series_id").head(12)
    else:
        base = base.groupby("series_id").head(12)
    sd = base.groupby("series_id")["y"].std().dropna()
    if sd.empty:
        return {}
    q = pd.qcut(sd.rank(method="first"), 3, labels=["low", "middle", "high"])
    return {k: str(v) for k, v in q.items()}


def _country_table(primary: pd.DataFrame, spec: ResearchSpec, ts: pd.Timestamp | None) -> list[dict[str, Any]]:
    pr = spec.predictive
    assert pr is not None
    out = []
    for h in pr.horizons:
        rows = pooled.matched_losses(primary, "ridge_A", "ridge_B" if "B" in pr.families else "ridge_A", h, ts)
        if rows.empty:
            continue
        pc = pooled.per_country(rows)
        skill = pooled.matched_losses(primary, "naive", "ridge_A", h, ts)
        sk = pooled.per_country(skill).set_index("country_iso3")["ratio"] if len(skill) else pd.Series(dtype=float)
        for r in pc.itertuples():
            out.append(
                {
                    "country_iso3": r.country_iso3,
                    "macro_region": macro_region(r.country_iso3),
                    "horizon": h,
                    "ratio_B_vs_A": float(r.ratio),
                    "ratio_A_vs_naive": float(sk.get(r.country_iso3, np.nan)),
                    "n_series": int(r.n_series),
                    "n_months": int(r.n_months),
                    "n_forecasts": int(r.n_forecasts),
                    "note": "descriptive per-country ratio; no per-country test is in the confirmatory family",
                }
            )
    return out
