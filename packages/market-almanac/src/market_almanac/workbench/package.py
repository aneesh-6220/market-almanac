"""Research packages: human report, RO-Crate 1.2 metadata, checksums, export and verification.

The package directory holds the specification, freeze record, results, pooled predictions and
per-group experiment artefacts. ``ro-crate-metadata.json`` describes them with schema.org terms
as RO-Crate 1.2 prescribes, including a ``CreateAction`` (who/what produced the results from
which inputs, with which software revision) so the provenance can be read by generic tools.
``SHA256SUMS`` lists every file; ``verify_package`` recomputes it.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from market_almanac.workbench.spec import FAMILY_MEANING, ResearchSpec

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.2/context"
RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.2"
SKIP = {"SHA256SUMS", "ro-crate-metadata.json"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name not in SKIP and not p.name.endswith(".tmp"))


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_report(spec: ResearchSpec, results: dict[str, Any]) -> str:
    lines = [
        f"# {spec.title}",
        "",
        f"Study `{spec.id}` · {spec.study_type} · **{spec.evidence_class}** · specification hash "
        f"`{spec.spec_hash()[:16]}`",
        "",
        f"**Question.** {spec.question}",
        "",
        f"**Hypothesis.** {spec.hypothesis}",
        "",
        f"**Estimand.** {spec.estimand}",
        "",
    ]
    if results.get("frozen"):
        code = results.get("freeze_code") or {}
        lines += [
            f"Frozen at {results.get('frozen_at')} from commit `{(code.get('git_commit') or '')[:12]}`; "
            f"analysis groups fixed by selection hash `{(results.get('selection_hash') or '')[:16]}` before any "
            "model was estimated on this population.",
            "",
        ]
    if spec.study_type == "predictive":
        pr = spec.predictive
        assert pr is not None
        lines += ["## Model families", ""]
        lines += [f"- **{f}**: {FAMILY_MEANING[f]}" for f in pr.families]
        lines += [
            "",
            f"Population: {results.get('n_groups')} commodity groups in {results.get('n_countries')} countries; "
            f"evaluation origins from {results.get('test_start') or 'the first rolling origin'}.",
            "",
            "## Pre-declared hypotheses",
            "",
            "Loss ratio = challenger / baseline mean squared error (country-balanced); below 1 favours the "
            f"challenger. p-values are {results['multiplicity']['method']}-adjusted within the family "
            f"{results['multiplicity']['family']}.",
            "",
            "| Hypothesis | Contrast | h | Countries | Months | Loss ratio | 95% CI (two-way bootstrap) | p (raw) | p (adj.) | Evidence |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for x in results.get("hypotheses", []):
            h, r = x["hypothesis"], x["result"]
            ci = r.get("ci_primary") or {}
            lines.append(
                f"| {h['id']} | {h['challenger']} vs {h['baseline']} | {h['horizon']} | {_fmt(r.get('n_countries'))} | "
                f"{_fmt(r.get('n_months'))} | {_fmt(r.get('loss_ratio'))} | "
                f"{_fmt(ci.get('ci_low'))}–{_fmt(ci.get('ci_high'))} | {_fmt(x.get('p_raw'), 4)} | "
                f"{_fmt(x.get('p_adjusted'), 4)} | {x['evidence']['class']} |"
            )
        lines += [
            "",
            "## Is price history itself skilful?",
            "",
            "| Baseline | h | Loss ratio (ridge A / baseline) | p (A better) | Countries |",
            "|---|---|---|---|---|",
        ]
        for s in results.get("baseline_skill", []):
            lines.append(
                f"| {s['baseline']} | {s['horizon']} | {_fmt(s.get('loss_ratio'))} | {_fmt(s.get('p_challenger_better'), 4)} | {_fmt(s.get('n_countries'))} |"
            )
        if results.get("variants"):
            lines += [
                "",
                "## Robustness and negative controls",
                "",
                "| Variant | Kind | Contrast | h | Loss ratio | p (challenger better) | Countries |",
                "|---|---|---|---|---|---|---|",
            ]
            for v in results["variants"]:
                lines.append(
                    f"| {v['variant']} | {v['kind']} | {v['contrast']} | {v['horizon']} | {_fmt(v.get('loss_ratio'))} | {_fmt(v.get('p_challenger_better'), 4)} | {_fmt(v.get('n_countries'))} |"
                )
        if results.get("heterogeneity"):
            lines += [
                "",
                "## Heterogeneity (exploratory; Benjamini–Hochberg q-values)",
                "",
                "| Hyp. | Dimension | Level | Loss ratio | q | Countries | Series |",
                "|---|---|---|---|---|---|---|",
            ]
            for v in results["heterogeneity"]:
                lines.append(
                    f"| {v['hypothesis']} | {v['dimension']} | {v['level']} | {_fmt(v.get('loss_ratio'))} | {_fmt(v.get('q_value_bh'), 3)} | {_fmt(v.get('n_countries'))} | {_fmt(v.get('n_series'))} |"
                )
    elif spec.study_type == "associational":
        a = results.get("associational", {})
        lines += [
            "## Estimates",
            "",
            a.get("interpretation", ""),
            "",
            "| Term | Coef. | SE | 95% CI | p |",
            "|---|---|---|---|---|",
        ]
        for t in a.get("terms", []):
            lines.append(
                f"| {t['term']} | {_fmt(t['coef'], 4)} | {_fmt(t['se'], 4)} | {_fmt(t['ci_low'], 4)}–{_fmt(t['ci_high'], 4)} | {_fmt(t['p_value'], 4)} |"
            )
        lines += [
            "",
            f"Observations {a.get('n_obs')}, series {a.get('n_series')}, months {a.get('n_periods')}, clusters {a.get('n_clusters')}.",
        ]
    else:
        lines += [
            "## Group summaries",
            "",
            "| Country | Commodity | Unit | Series | Trend %/yr | Volatility (sd Δlog) | Seasonal amplitude | Peak month |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for g in results.get("descriptive", {}).get("groups", []):
            lines.append(
                f"| {g['country_iso3']} | {g['commodity_name']} | {g['unit']} | {g['series']} | {_fmt(g.get('median_trend_pct_per_year'), 1)} | {_fmt(g.get('median_volatility_sd_dlog'))} | {_fmt(g.get('median_seasonal_amplitude_log'))} | {_fmt(g.get('modal_seasonal_peak_month'))} |"
            )
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in results.get("limitations", [])]
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        f"uv run market-almanac research run {spec.id}.yaml          # re-executes on the frozen snapshots",
        f"uv run market-almanac research verify data/studies/live/{spec.id}",
        "```",
        "",
    ]
    return "\n".join(lines)


def ro_crate(spec: ResearchSpec, root: Path, results: dict[str, Any]) -> dict[str, Any]:
    files = _files(root)
    now = datetime.now(UTC).isoformat()
    code = results.get("code") or {}
    software_id = "https://github.com/aneesh-6220/market-almanac"
    data_entities = []
    inputs = []
    for key, snap in (results.get("data_snapshots") or {}).items():
        eid = f"#snapshot-{key.replace(':', '-')}-{snap.get('snapshot_id')}"
        inputs.append({"@id": eid})
        data_entities.append(
            {
                "@id": eid,
                "@type": "Dataset",
                "name": f"{key} snapshot {snap.get('snapshot_id')}",
                "identifier": snap.get("snapshot_id"),
                "description": "Immutable Market Almanac lake snapshot (not redistributed in this package).",
                "sha256": snap.get("file_sha256") or snap.get("observation_hash") or snap.get("content_hash"),
            }
        )
    file_entities = [
        {
            "@id": str(p.relative_to(root)),
            "@type": "File",
            "contentSize": str(p.stat().st_size),
            "sha256": _sha256(p),
            "encodingFormat": {
                ".json": "application/json",
                ".parquet": "application/vnd.apache.parquet",
                ".md": "text/markdown",
                ".yaml": "application/yaml",
            }.get(p.suffix, "application/octet-stream"),
        }
        for p in files
    ]
    return {
        "@context": RO_CRATE_CONTEXT,
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": RO_CRATE_PROFILE},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": spec.title,
                "description": spec.question,
                "identifier": spec.id,
                "datePublished": now,
                "license": {"@id": "https://opensource.org/licenses/MIT"},
                "keywords": ["food prices", "forecast evaluation", spec.study_type, spec.evidence_class],
                "hasPart": [{"@id": f["@id"]} for f in file_entities],
                "mentions": [{"@id": "#run"}],
            },
            {
                "@id": "#run",
                "@type": "CreateAction",
                "name": f"Execution of research specification {spec.id}",
                "instrument": {"@id": software_id},
                "object": inputs,
                "result": [{"@id": "results.json"}] if (root / "results.json").exists() else [],
                "startTime": (results.get("execution") or {}).get("started_at"),
                "endTime": (results.get("execution") or {}).get("finished_at"),
            },
            {
                "@id": software_id,
                "@type": "SoftwareApplication",
                "name": "Market Almanac",
                "version": results.get("software_version"),
                "identifier": code.get("git_commit"),
                "license": {"@id": "https://opensource.org/licenses/MIT"},
            },
            *data_entities,
            *file_entities,
        ],
    }


def write_package(settings: Any, spec: ResearchSpec, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "spec.yaml").write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True))
    results = json.loads((root / "results.json").read_text()) if (root / "results.json").exists() else {}
    (root / "report.md").write_text(render_report(spec, results))
    (root / "ro-crate-metadata.json").write_text(json.dumps(ro_crate(spec, root, results), indent=1, default=str))
    sums = [f"{_sha256(p)}  {p.relative_to(root)}" for p in _files(root)]
    sums.append(f"{_sha256(root / 'ro-crate-metadata.json')}  ro-crate-metadata.json")
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return root


def verify_package(root: Path) -> dict[str, Any]:
    """Recompute every checksum listed in SHA256SUMS; report missing, changed and unlisted files."""
    root = Path(root)
    listed: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if line.strip():
            h, name = line.split("  ", 1)
            listed[name] = h
    bad, missing = [], []
    for name, h in listed.items():
        p = (root / name).resolve()
        if root.resolve() not in p.parents:
            bad.append(name)  # a listed path that escapes the package is never read
            continue
        if not p.exists():
            missing.append(name)
        elif _sha256(p) != h:
            bad.append(name)
    present = {str(p.relative_to(root)) for p in _files(root)} | {"ro-crate-metadata.json"}
    unlisted = sorted(present - set(listed))
    return {"files": len(listed), "changed": bad, "missing": missing, "unlisted": unlisted, "ok": not (bad or missing)}


def export_package(root: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for p in [*_files(root), root / "ro-crate-metadata.json", root / "SHA256SUMS"]:
            if p.exists():
                tar.add(p, arcname=f"{root.name}/{p.relative_to(root)}")
    return out
