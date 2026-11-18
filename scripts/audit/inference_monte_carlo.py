"""Audit v1.1, Audit 3: Monte Carlo evaluation of the Atlas v1 inference procedures.

Simulates (country x origin-month) panels of squared forecast errors for a baseline (A) and a
challenger (B) and measures, per scenario:

* rejection rate of the one-sided Diebold-Mariano test (protocol: Newey-West, max(h-1,
  floor(4(T/100)^(2/9))) lags, HLN correction, t(T-1)) on country-balanced monthly differentials;
* coverage of the 95% two-way (country x moving month block) percentile bootstrap interval for
  the country-balanced loss ratio, and of two alternatives: month-block-only and country-only;
* rejection rate of an alternative: a two-way cluster-robust (Cameron-Gelbach-Miller) t-test
  of the same mean differential, t(min(C,T)-1) reference.

The DGP (one row per series i in country c, month t):
    log sigma_ct = mu_c + g_t + u_ct               mu_c ~ N(0, het); g_t AR(1) shared; u_ct AR(1) own
    eps_it       = sqrt(k) w_ct + sqrt(1-k) xi_it   within-country common shock, optional t(df) tails
    z_it         = MA(q) of eps, q = h (h-step targets measured from P_{t-1} overlap h months)
    e_A = sigma_ct z_A ;  e_B = sigma_ct sqrt(theta_c) z_B,  corr(z_A, z_B) = rho_ab
    loss = e^2, averaged over the series of a country-month.
The population country-balanced ratio equals E[theta_c] (theta_c independent of scale), which is
the truth used for coverage. Everything is written from scratch with numpy/scipy; the bootstrap
reproduces ``workbench.pooled.two_way_bootstrap`` (checked in ``--selfcheck``).

    uv run python -I scripts/audit/inference_monte_carlo.py --reps 1000 --boot 499 \
        --out docs/audits/evidence/atlas_v1/inference_monte_carlo.json
"""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Scenario:
    name: str
    C: int = 39
    T: int = 57
    h: int = 1
    m: int = 8  # series per country-month
    theta: float = 1.0  # mean challenger/baseline MSE ratio (1 = null)
    theta_sd: float = 0.0  # log-sd of country-specific effects (persistent effect heterogeneity)
    het: float = 0.5  # sd of persistent country log-scale
    g_sd: float = 0.5  # sd of shared (global) month log-scale shocks
    g_rho: float = 0.5  # AR(1) of the shared shock
    u_sd: float = 0.3  # sd of country-specific month log-scale shocks
    u_rho: float = 0.5
    k: float = 0.3  # within-country-month error correlation
    df: float = 0.0  # 0 = Gaussian errors, else Student-t(df) standardised
    rho_ab: float = 0.9  # correlation of A and B errors (nested models)
    missing: float = 0.0  # share of country-months missing at random
    late_entry: float = 0.0  # share of countries that enter half-way through the window
    outlier_scale: float = 0.0  # >0: one country gets log-scale +outlier_scale in the last 8 months
    block: int = 0  # bootstrap block length; 0 = protocol rule max(h, round(T^(1/3)))


def _t(rng: np.random.Generator, df: float, size: tuple[int, ...]) -> np.ndarray:
    if df <= 0:
        return rng.standard_normal(size)
    return rng.standard_t(df, size) / math.sqrt(df / (df - 2))


def _ar(rng: np.random.Generator, rho: float, sd: float, shape: tuple[int, ...]) -> np.ndarray:
    e = rng.standard_normal(shape) * sd * math.sqrt(1 - rho**2)
    x = np.empty(shape)
    x[..., 0] = rng.standard_normal(shape[:-1]) * sd
    for t in range(1, shape[-1]):
        x[..., t] = rho * x[..., t - 1] + e[..., t]
    return x


def simulate(s: Scenario, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    C, T, m, q = s.C, s.T, s.m, s.h
    logsig = (
        rng.standard_normal((C, 1)) * s.het
        + _ar(rng, s.g_rho, s.g_sd, (1, T))
        + (_ar(rng, s.u_rho, s.u_sd, (C, T)) if s.u_sd > 0 else 0.0)
    )
    if s.outlier_scale > 0:
        logsig[0, -8:] += s.outlier_scale
    theta_c = s.theta * np.exp(rng.standard_normal((C, 1)) * s.theta_sd - s.theta_sd**2 / 2)

    def errors() -> tuple[np.ndarray, np.ndarray]:
        sh = (C, T + q, m)
        wa = _t(rng, s.df, (C, T + q, 1))
        xa = _t(rng, s.df, sh)
        xb = s.rho_ab * xa + math.sqrt(1 - s.rho_ab**2) * _t(rng, s.df, sh)
        wb = s.rho_ab * wa + math.sqrt(1 - s.rho_ab**2) * _t(rng, s.df, (C, T + q, 1))
        ea = math.sqrt(s.k) * wa + math.sqrt(1 - s.k) * xa
        eb = math.sqrt(s.k) * wb + math.sqrt(1 - s.k) * xb
        za = sum(ea[:, j : j + T] for j in range(q + 1)) / math.sqrt(q + 1)  # MA(q) overlap
        zb = sum(eb[:, j : j + T] for j in range(q + 1)) / math.sqrt(q + 1)
        return za, zb

    za, zb = errors()
    sig = np.exp(logsig)[:, :, None]
    la = ((sig * za) ** 2).mean(axis=2)
    lb = ((sig * np.sqrt(theta_c)[:, :, None] * zb) ** 2).mean(axis=2)
    mask = np.ones((C, T), bool)
    if s.missing > 0:
        mask &= rng.random((C, T)) >= s.missing
    if s.late_entry > 0:
        late = rng.random(C) < s.late_entry
        mask[late, : T // 2] = False
    mask[:, mask.sum(0) == 0] = True  # keep every month represented
    la[~mask] = np.nan
    lb[~mask] = np.nan
    return la, lb


# ---------------------------------------------------------------------------------- procedures
def dm(d: np.ndarray, h: int) -> float:
    """One-sided p for E d > 0 (challenger better)."""
    n = len(d)
    q = max(h - 1, math.floor(4 * (n / 100) ** (2 / 9)))
    e = d - d.mean()
    v = e @ e / n + sum(2 * (1 - k / (q + 1)) * (e[k:] @ e[:-k]) / n for k in range(1, q + 1))
    if v <= 0:
        return float("nan")
    st = d.mean() / math.sqrt(v / n) * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return float(stats.t.sf(st, n - 1))


def cgm(la: np.ndarray, lb: np.ndarray) -> float:
    """Two-way (country, month) cluster-robust one-sided p for the month-balanced mean of d_ct."""
    d = la - lb
    ok = np.isfinite(d)
    n_t = ok.sum(0)
    w = np.where(ok, 1.0 / (n_t[None, :] * ok.shape[1]), 0.0)
    dbar = float(np.nansum(w * np.nan_to_num(d)))
    e = np.where(ok, d - dbar, 0.0)
    we = w * e
    v = (we.sum(1) ** 2).sum() + (we.sum(0) ** 2).sum() - (we**2).sum()
    if v <= 0:
        return float("nan")
    G = min(d.shape)
    return float(stats.t.sf(dbar / math.sqrt(v), G - 1))


def boot(
    la: np.ndarray, lb: np.ndarray, h: int, B: int, rng: np.random.Generator, kind: str, block: int
) -> tuple[float, float]:
    C, T = la.shape
    L = block or max(h, round(T ** (1 / 3)))
    nb = math.ceil(T / L)
    if kind in ("two_way", "month"):
        starts = rng.integers(0, T - L + 1, (B, nb))
        ti = (starts[:, :, None] + np.arange(L)).reshape(B, -1)[:, :T]
    else:
        ti = np.broadcast_to(np.arange(T), (B, T))
    ci = rng.integers(0, C, (B, C)) if kind in ("two_way", "country") else np.broadcast_to(np.arange(C), (B, C))
    sa = la[ci[:, :, None], ti[:, None, :]]
    sb = lb[ci[:, :, None], ti[:, None, :]]
    with np.errstate(invalid="ignore", divide="ignore"):
        ma, mb = np.nanmean(sa, axis=1), np.nanmean(sb, axis=1)
        ok = np.isfinite(ma) & np.isfinite(mb)
        r = np.where(ok, mb, 0).sum(1) / np.where(ok, ma, 0).sum(1)
    r = r[np.isfinite(r)]
    return float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))


def ratio(la: np.ndarray, lb: np.ndarray) -> float:
    return float(np.nansum(np.nanmean(lb, 0)) / np.nansum(np.nanmean(la, 0)))


def run(args: tuple[Scenario, int, int, int]) -> dict:
    s, reps, B, seed = args
    rng = np.random.default_rng(seed)
    truth = s.theta
    rec = {k: [] for k in ("dm", "cgm", "cov2", "covm", "covc", "rej2", "width2", "ratio", "rule", "rule_holm")}
    t0 = time.time()
    for _ in range(reps):
        la, lb = simulate(s, rng)
        ma, mb = np.nanmean(la, 0), np.nanmean(lb, 0)
        rec["dm"].append(dm(ma - mb, s.h))
        rec["cgm"].append(cgm(la, lb))
        rec["ratio"].append(ratio(la, lb))
        for kind, key in (("two_way", "cov2"), ("month", "covm"), ("country", "covc")):
            lo, hi = boot(la, lb, s.h, B, rng, kind, s.block)
            rec[key].append(lo <= truth <= hi)
            if kind == "two_way":
                rec["rej2"].append(hi < 1)
                rec["width2"].append(hi - lo)
                p = rec["dm"][-1]
                # protocol decision rule "improvement": DM p < alpha AND two-way upper bound < 1;
                # with Holm over two hypotheses the smaller p must clear alpha/2
                rec["rule"].append(bool(np.isfinite(p) and p < 0.05 and hi < 1))
                rec["rule_holm"].append(bool(np.isfinite(p) and p < 0.025 and hi < 1))
    R = reps

    def rate(x: list) -> dict:
        a = np.asarray(x, float)
        a = a[np.isfinite(a)]
        p = float(a.mean())
        se = math.sqrt(p * (1 - p) / len(a)) if len(a) else float("nan")
        return {"rate": p, "mc_se": se, "n": len(a)}

    out = {
        "scenario": asdict(s),
        "truth_ratio": truth,
        "reps": R,
        "bootstrap_draws": B,
        "dm_reject_5pct_one_sided": rate([p < 0.05 for p in rec["dm"] if np.isfinite(p)]),
        "dm_reject_10pct_one_sided": rate([p < 0.10 for p in rec["dm"] if np.isfinite(p)]),
        "cgm_reject_5pct_one_sided": rate([p < 0.05 for p in rec["cgm"] if np.isfinite(p)]),
        "two_way_coverage_95": rate(rec["cov2"]),
        "month_block_coverage_95": rate(rec["covm"]),
        "country_only_coverage_95": rate(rec["covc"]),
        "two_way_upper_below_1": rate(rec["rej2"]),
        "decision_rule_improvement": rate(rec["rule"]),
        "decision_rule_improvement_holm_bound": rate(rec["rule_holm"]),
        "two_way_median_width": float(np.median(rec["width2"])),
        "ratio_median": float(np.median(rec["ratio"])),
        "ratio_mean": float(np.mean(rec["ratio"])),
        "seconds": time.time() - t0,
    }
    return out


BASE = Scenario("baseline (study-like: C=39, T=57, h=1, shared AR(1) month shocks)")


def scenarios() -> list[Scenario]:
    b = BASE
    S = [b]
    S += [replace(b, name=f"non-null theta={t}", theta=t) for t in (0.98, 0.95, 0.90)]
    S += [
        replace(b, name="no month shocks", g_sd=0.0, u_sd=0.0),
        replace(b, name="iid shared month shocks", g_rho=0.0),
        replace(b, name="strongly persistent shared shocks (rho=0.9, sd=0.8)", g_rho=0.9, g_sd=0.8),
        replace(b, name="no shared shocks (country-specific only, sd=0.6)", g_sd=0.0, u_sd=0.6),
        replace(b, name="no country heterogeneity", het=0.0),
        replace(b, name="strong country heterogeneity (sd=1.2)", het=1.2),
        replace(b, name="heterogeneous effects, null on average (theta_sd=0.15)", theta_sd=0.15),
        replace(b, name="heterogeneous effects, theta=0.95, theta_sd=0.15", theta=0.95, theta_sd=0.15),
        replace(b, name="unbalanced: 30% country-months missing", missing=0.3),
        replace(b, name="unbalanced: 30% countries enter half-way", late_entry=0.3),
        replace(b, name="heavy tails t(4)", df=4.0),
        replace(b, name="heavy tails t(2.5)", df=2.5),
        replace(b, name="one explosive country (scale x e^2.5 in last 8 months)", outlier_scale=2.5),
        replace(b, name="explosive country + t(2.5) tails", outlier_scale=2.5, df=2.5),
        replace(b, name="h=3 (MA(3) overlap)", h=3),
        replace(b, name="h=3, theta=0.95", h=3, theta=0.95),
        replace(b, name="T=24", T=24),
        replace(b, name="T=120", T=120),
        replace(b, name="T=24, theta=0.95", T=24, theta=0.95),
        replace(b, name="C=5", C=5),
        replace(b, name="C=15", C=15),
        replace(b, name="C=80", C=80),
        replace(b, name="block length 1", block=1),
        replace(b, name="block length 2", block=2),
        replace(b, name="block length 8", block=8),
        replace(b, name="block length 12", block=12),
        replace(b, name="h=3, block length 2", h=3, block=2),
    ]
    return S


def selfcheck() -> None:
    """The vectorised bootstrap is the same algorithm as workbench.pooled.two_way_bootstrap."""
    import pandas as pd

    from market_almanac.workbench.pooled import two_way_bootstrap

    rng = np.random.default_rng(1)
    la, lb = simulate(BASE, rng)
    C, T = la.shape
    rows = [
        {
            "country_iso3": f"C{c:02d}",
            "origin": pd.Timestamp("2022-01-01") + pd.DateOffset(months=t),
            "loss_a": la[c, t],
            "loss_b": lb[c, t],
        }
        for c in range(C)
        for t in range(T)
        if np.isfinite(la[c, t])
    ]
    ref = two_way_bootstrap(pd.DataFrame(rows), 1, 4000, 7, 0.05)
    mine = boot(la, lb, 1, 4000, np.random.default_rng(7), "two_way", 0)
    print("project two-way bootstrap:", ref["ci_low"], ref["ci_high"], "| audit re-implementation:", mine)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--boot", type=int, default=499)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        return 0
    S = [s for s in scenarios() if not a.only or any(o in s.name for o in a.only)]
    jobs = [(s, a.reps, a.boot, 20261118 + i) for i, s in enumerate(S)]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs))
    for r in res:
        print(
            f"{r['scenario']['name'][:58]:58} DM {r['dm_reject_5pct_one_sided']['rate']:.3f} "
            f"CGM {r['cgm_reject_5pct_one_sided']['rate']:.3f} cov2 {r['two_way_coverage_95']['rate']:.3f} "
            f"covM {r['month_block_coverage_95']['rate']:.3f} covC {r['country_only_coverage_95']['rate']:.3f} "
            f"up<1 {r['two_way_upper_below_1']['rate']:.3f} rule {r['decision_rule_improvement']['rate']:.3f} "
            f"w {r['two_way_median_width']:.3f}"
        )
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"generated_by": "scripts/audit/inference_monte_carlo.py", "results": res}, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
