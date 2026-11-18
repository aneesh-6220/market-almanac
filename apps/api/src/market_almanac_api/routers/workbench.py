"""Research workbench endpoints: specification validation and published study results.

Nothing here executes an analysis. Validation parses and checks a specification (bounded body
size, safe YAML loader, no file or network access); studies are read from published summaries.
Running a study is a local, reproducible CLI job (``market-almanac research run``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from market_almanac.config import Settings
from market_almanac.workbench.spec import FAMILY_MEANING, NEGATIVE_CONTROLS, ROBUSTNESS, SpecError, parse_spec
from market_almanac_api.deps import settings_dep

router = APIRouter(prefix="/api/v1/workbench", tags=["research"])
MAX_SPEC_BYTES = 64 * 1024
STUDY_ID = r"^[a-z0-9][a-z0-9\-]{2,63}$"


def published_dir() -> FsPath:
    from market_almanac.workbench import publish

    return publish.PUBLISHED_DIR


def _published(settings: Settings) -> dict[str, FsPath]:
    """Published summaries: packaged with the code, overridden by locally generated ones."""
    out: dict[str, FsPath] = {}
    d = published_dir()
    if settings.market_almanac_mode.value == "live" and d.exists():
        out.update({p.stem: p for p in d.glob("*.json")})
    local = FsPath(settings.data_dir) / "studies" / settings.market_almanac_mode.value
    for p in local.glob("*/published.json") if local.exists() else []:
        out[p.parent.name] = p
    return out


@router.post("/validate")
async def validate(request: Request) -> dict[str, Any]:
    """Validate a research specification (YAML or JSON text). Returns problems instead of running anything."""
    if int(request.headers.get("content-length") or 0) > MAX_SPEC_BYTES:
        raise HTTPException(413, f"specification larger than {MAX_SPEC_BYTES // 1024} KB")
    body = await request.body()
    if len(body) > MAX_SPEC_BYTES:
        raise HTTPException(413, f"specification larger than {MAX_SPEC_BYTES // 1024} KB")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "specification must be UTF-8 text") from exc
    try:
        spec = parse_spec(text)
    except SpecError as exc:
        problems = [p for p in str(exc).splitlines() if p.strip()]
        return {"valid": False, "problems": problems[:50]}
    return {
        "valid": True,
        "problems": [],
        "spec_hash": spec.spec_hash(),
        "id": spec.id,
        "study_type": spec.study_type,
        "evidence_class": spec.evidence_class,
        "countries": spec.population.countries,
        "run_locally": [
            f"uv run market-almanac research preview {spec.id}.yaml",
            *(
                [f"uv run market-almanac research freeze {spec.id}.yaml"]
                if spec.evidence_class == "confirmatory"
                else []
            ),
            f"uv run market-almanac research run {spec.id}.yaml",
        ],
    }


@router.get("/options")
def options() -> dict[str, Any]:
    """Choices the specification format accepts (for building forms)."""
    return {
        "families": FAMILY_MEANING,
        "robustness": list(ROBUSTNESS),
        "negative_controls": list(NEGATIVE_CONTROLS),
        "study_types": ["descriptive", "associational", "predictive"],
        "not_supported": {"causal": "No estimator with identification diagnostics is implemented in this release."},
    }


@router.get("/studies")
def studies(s: Annotated[Settings, Depends(settings_dep)]) -> list[dict[str, Any]]:
    out = []
    for _sid, p in sorted(_published(s).items()):
        d = json.loads(p.read_text())
        keys = ("id", "title", "study_type", "evidence_class", "question", "headline", "published_at", "spec_hash")
        out.append({k: d.get(k) for k in (*keys, "frozen", "n_countries")})
    return out


@router.get("/studies/{study_id}")
def study(
    study_id: Annotated[str, Path(pattern=STUDY_ID)], s: Annotated[Settings, Depends(settings_dep)]
) -> dict[str, Any]:
    p = _published(s).get(study_id)
    if p is None or not re.fullmatch(STUDY_ID, study_id):
        raise HTTPException(404, f"no published study {study_id}")
    return json.loads(p.read_text())
