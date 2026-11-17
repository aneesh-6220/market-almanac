"""Human-readable research reports and machine-readable exports for experiments."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

VERDICT_LABEL = {
    "improved": "Environmental features IMPROVED prediction",
    "not_improved": "Environmental features did NOT improve prediction",
    "inconsistent": "Results were INCONSISTENT",
    "insufficient_evidence": "Evidence was INSUFFICIENT",
}


def _f(x: Any, nd: int = 4) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}g}"
    return str(x)


def markdown_report(results: dict[str, Any]) -> str:
    r = results
    c = r.get("conclusion", {})
    lines = [f"# ShockTrace experiment report: {r['name']}", ""]
    if r.get("synthetic"):
        lines += [
            "> **SYNTHETIC DEMO DATA.** These results describe a fictional data-generating process and say "
            "nothing about real markets.",
            "",
        ]
    lines += [
        f"- Experiment ID: `{r['experiment_id']}`  ",
        f"- Mode: `{r['mode']}` · created {r['created_at']}  ",
        f"- Configuration hash: `{r.get('config_hash')}` · software {r.get('manifest', {}).get('software_version')}",
        "",
        "## Conclusion",
        "",
        f"**{VERDICT_LABEL.get(c.get('verdict', ''), c.get('verdict'))}.** {c.get('statement', '')}",
        "",
        f"_Decision rule:_ {c.get('decision_rule', '')}",
        "",
        f"_{c.get('causal_disclaimer', '')}_",
        "",
        "| Task | h | Baseline (A) | Enhanced (B) | Loss ratio B/A | Verdict | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in c.get("primary_comparisons", []):
        lines.append(
            f"| {p['task']} | {p['horizon']} | {p['model_a']} | {p['model_b']} | "
            f"{_f(p.get('relative_loss_b_vs_a'))} | {p['verdict']} | {p['reason']} |"
        )
    d = r.get("data", {})
    lines += [
        "",
        "## Data",
        "",
        f"- Eligible series: {d.get('n_series', 0)}; origins {d.get('first_origin')} → {d.get('last_origin')}",
        "",
    ]
    for name, snap in r.get("manifest", {}).get("snapshots", {}).items():
        lines.append(
            f"- `{name}` snapshot `{snap.get('snapshot_id')}` ({snap.get('row_count')} rows, retrieved "
            f"{snap.get('retrieved_at_min')} – {snap.get('retrieved_at_max')})"
        )
    lines += ["", "## Results by task", ""]
    for t in r.get("tasks", []):
        lines += [
            f"### {t['task'].title()} · horizon {t['horizon']} month(s)"
            + (f" · spike threshold {t['threshold']:.0%}" if t.get("threshold") else ""),
            "",
        ]
        if t.get("status") != "ok":
            lines += [f"Insufficient evidence: {t.get('reason', '')}", ""]
            continue
        lines.append(
            f"Test period {t['test_period'][0]} → {t['test_period'][1]}, {t['n_test_periods']} origin "
            f"months, {t['n_test_rows']} forecasts, {t['n_series']} series."
        )
        lines.append("")
        if t["task"] == "regression":
            lines += [
                "| Model | MAE | RMSE | MAE / naive | Bias | Direction acc. | 80% PI coverage |",
                "|---|---|---|---|---|---|---|",
            ]
            for mname, met in t["models"].items():
                cov = met.get("interval_coverage", {}).get("80", {}).get("empirical")
                lines.append(
                    f"| {mname} | {_f(met['mae'])} | {_f(met['rmse'])} | {_f(met.get('relative_mae'))} | "
                    f"{_f(met['bias'])} | {_f(met.get('directional_accuracy'))} | {_f(cov)} |"
                )
        else:
            lines += [
                "| Model | Brier | Brier skill | Log loss | PR-AUC | Precision | Recall | F1 | Events |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for mname, met in t["models"].items():
                lines.append(
                    f"| {mname} | {_f(met['brier'])} | {_f(met.get('brier_skill'))} | {_f(met.get('log_loss'))} | "
                    f"{_f(met.get('pr_auc'))} | {_f(met.get('precision'))} | {_f(met.get('recall'))} | "
                    f"{_f(met.get('f1'))} | {met.get('positives')} |"
                )
        lines += [
            "",
            "| Role | A | B | Loss ratio | 95% block-bootstrap CI | DM p (B better) | Verdict |",
            "|---|---|---|---|---|---|---|",
        ]
        for cmp in t.get("comparisons", []):
            b = cmp["bootstrap_loss_ratio"]
            ci = f"[{_f(b.get('ci_low'))}, {_f(b.get('ci_high'))}]" if b.get("ci_low") is not None else "—"
            lines.append(
                f"| {cmp['role']} | {cmp['model_a']} | {cmp['model_b']} | {_f(cmp.get('relative_loss_b_vs_a'))} "
                f"| {ci} | {_f(cmp['dm'].get('p_value_b_better'))} | {cmp['verdict']} |"
            )
        lines.append("")
    if r.get("sensitivity"):
        lines += [
            "## Spike-threshold sensitivity (logit A vs B)",
            "",
            "| h | Threshold | Events | Loss ratio B/A | DM p | Verdict |",
            "|---|---|---|---|---|---|",
        ]
        for s in r["sensitivity"]:
            lines.append(
                f"| {s['horizon']} | {s['threshold']:.0%} | {s.get('positives', '—')} | "
                f"{_f(s.get('relative_loss_b_vs_a'))} | {_f(s.get('dm_p_b_better'))} | "
                f"{s.get('verdict', s.get('status'))} |"
            )
        lines.append("")
    lines += ["## Limitations", ""] + [f"- {x}" for x in r.get("limitations", [])]
    if r.get("warnings"):
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    lines += ["", "## Reproduce", "", "```bash", f"shocktrace reproduce {r['experiment_id']}", "```", ""]
    return "\n".join(lines)


def export_bundle(experiment_dir: Path) -> bytes:
    """Zip of results.json, manifest.json, config.json, predictions.csv and report.md."""
    buf = io.BytesIO()
    results = json.loads((experiment_dir / "results.json").read_text())
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("results.json", "manifest.json", "config.json"):
            p = experiment_dir / name
            if p.exists():
                z.write(p, name)
        pp = experiment_dir / "predictions.parquet"
        if pp.exists():
            z.writestr("predictions.csv", pd.read_parquet(pp).to_csv(index=False))
        z.writestr("report.md", markdown_report(results))
        z.writestr(
            "README.txt",
            "ShockTrace experiment export. Re-run with: shocktrace reproduce "
            f"{results['experiment_id']}\n" + ("SYNTHETIC DEMO DATA\n" if results.get("synthetic") else ""),
        )
    return buf.getvalue()
