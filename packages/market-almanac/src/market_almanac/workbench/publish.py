"""Published study summaries: the subset of a study's results that the public API serves.

A summary is derived statistics (loss ratios, test statistics, counts, hashes), not observations,
so it can ship with the code and be served without the data lake. Per-forecast predictions stay
in the study package (``research export``), which is where independent recalculation starts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_almanac.workbench.spec import FAMILY_MEANING, ResearchSpec

PUBLISHED_DIR = Path(__file__).resolve().parents[1] / "research" / "published"
EVIDENCE_TEXT = {
    "improvement": "improvement established",
    "improvement_fragile": "improvement, but fragile",
    "deterioration": "forecasts got worse",
    "not_established": "no improvement established",
    "insufficient_data": "insufficient data",
}


def headline(spec: ResearchSpec, results: dict[str, Any]) -> str:
    if spec.study_type == "predictive":
        parts = []
        for h in results.get("hypotheses", []):
            r, hy = h["result"], h["hypothesis"]
            ratio = r.get("loss_ratio")
            pct = f"{(ratio - 1) * 100:+.1f}% loss" if ratio is not None else "no estimate"
            parts.append(
                f"{hy['id']} (h={hy['horizon']}): "
                f"{EVIDENCE_TEXT.get(h['evidence']['class'], h['evidence']['class'])} ({pct})"
            )
        return (
            f"{results.get('n_groups')} commodity groups in {results.get('n_countries')} countries. "
            + "; ".join(parts)
            + "."
        )
    if spec.study_type == "descriptive":
        g = results.get("descriptive", {}).get("groups", [])
        return f"Descriptive summary of {len(g)} commodity groups in {len({x['country_iso3'] for x in g})} countries."
    a = results.get("associational", {})
    return f"Associational panel estimate on {a.get('n_obs')} series-months; not causal."


def build_summary(spec: ResearchSpec, results: dict[str, Any], freeze: dict[str, Any] | None) -> dict[str, Any]:
    out = {
        "id": spec.id,
        "title": spec.title,
        "study_type": spec.study_type,
        "evidence_class": spec.evidence_class,
        "question": spec.question,
        "hypothesis": spec.hypothesis,
        "estimand": spec.estimand,
        "spec_hash": spec.spec_hash(),
        "spec": spec.model_dump(mode="json"),
        "families": {f: FAMILY_MEANING[f] for f in spec.predictive.families} if spec.predictive else None,
        "headline": headline(spec, results),
        "published_at": datetime.now(UTC).isoformat(),
        "frozen": freeze is not None,
        "freeze": {
            k: freeze.get(k)
            for k in ("frozen_at", "code", "selection_hash", "spec_hash", "statement", "software_version")
        }
        if freeze
        else None,
        "n_countries": results.get("n_countries") or len({g.get("country_iso3") for g in results.get("groups", [])}),
        "results": {k: v for k, v in results.items() if k not in ("spec",)},
    }
    return out


def publish(study_dir: Path, spec: ResearchSpec, package: bool) -> Path:
    results = json.loads((study_dir / "results.json").read_text())
    freeze_p = study_dir / "freeze.json"
    freeze = json.loads(freeze_p.read_text()) if freeze_p.exists() else None
    summary = build_summary(spec, results, freeze)
    text = json.dumps(summary, indent=1, default=str)
    (study_dir / "published.json").write_text(text)
    if package:
        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
        target = PUBLISHED_DIR / f"{spec.id}.json"
        target.write_text(text)
        return target
    return study_dir / "published.json"
