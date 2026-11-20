"""The economic-context artefact: building it under a redistribution policy, pinning it, installing it.

Which observations may be published is decided **per source** by the licence record each source carries in the
snapshot manifest (:data:`market_almanac.context.refresh.LICENCES`):

* ``redistribution: "confirmed"``  the observations are included in the public artefact;
* anything else (``"unconfirmed"``, ``"restricted"``) the observations are **withheld**. The artefact then holds
  metadata only: the series table (identifiers, coverage, bases, freshness), the source citations and licence
  records, the source vintages, the SHA-256 of every retrieved response and of every series' observations, and the
  instructions to retrieve the data oneself (``market-almanac context refresh``) and check it against those hashes.

``include_unconfirmed=True`` builds the complete artefact for private use (a deployment the operator controls, or after
the provider's permission is on record); the manifest says so (``data_included``), and the public
:func:`build_context_bundle` default never does it implicitly.

Installing is the shared, hash-verified, never-overwrite installer in :mod:`market_almanac.data.public_bundle`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.context import ARTEFACT_FORMAT
from market_almanac.context.store import (
    DEFS_FILE,
    MANIFEST_FILE,
    OBS_FILE,
    REJECTED_FILE,
    SERIES_FILE,
    ContextSnapshot,
    ContextStore,
    ContextStoreError,
)
from market_almanac.data.public_bundle import (
    CONTEXT_BUNDLE_FORMAT,
    BundleError,
    _write_bundle,
    install_bundle,
)

RELEASE_FILE = Path(__file__).with_name("context_release.json")
SERIES_HASHES = "series_hashes.json"
RETRIEVAL = "RETRIEVAL.md"

CONTEXT_ATTRIBUTION = [
    "Consumer prices and exchange rates: International Monetary Fund, CPI and ER datasets "
    "(https://data.imf.org). Used under the IMF copyright and usage terms "
    "(https://www.imf.org/en/About/copyright-and-terms).",
    "Commodity prices: The World Bank, Commodity Price Data (The Pink Sheet), compiled from the third-party sources "
    "named in the workbook (https://www.worldbank.org/en/research/commodity-markets).",
]

assert ARTEFACT_FORMAT == CONTEXT_BUNDLE_FORMAT


def series_hashes(obs: pd.DataFrame) -> dict[str, str]:
    """SHA-256 of each series' observations ("YYYY-MM,value" lines, ``repr``-exact floats), so data a user retrieves
    themselves can be checked against the published artefact without the artefact containing the values."""
    out: dict[str, str] = {}
    for key, g in obs.sort_values(["series_key", "period"]).groupby("series_key", sort=True):
        h = hashlib.sha256()
        for p, v in zip(g["period"], g["value"], strict=True):
            h.update(f"{pd.Timestamp(p).strftime('%Y-%m')},{float(v)!r}\n".encode())
        out[str(key)] = h.hexdigest()
    return out


def _provider_policy(manifest: dict[str, Any], include_unconfirmed: bool) -> dict[str, bool]:
    return {
        str(s["provider"]): bool(include_unconfirmed or s.get("licence", {}).get("redistribution") == "confirmed")
        for s in manifest.get("sources", [])
    }


def _retrieval_text(manifest: dict[str, Any], withheld: list[str]) -> str:
    lines = [
        "# Retrieving the economic-context data",
        "",
        f"Snapshot `{manifest['snapshot_id']}` (observation hash `{manifest['observation_hash']}`).",
        "",
        *(
            [
                "This artefact does not contain the observations of: " + ", ".join(withheld) + ".",
                "Their redistribution is not confirmed (see `manifest.json`, `sources[].licence`), so only metadata,",
                "citations, retrieval instructions and hashes are published. To obtain the data:",
            ]
            if withheld
            else [
                "This artefact contains the observations of every source (see `manifest.json`, `sources[].licence`",
                "for each source's terms and attribution). To retrieve the data yourself and compare it:",
            ]
        ),
        "",
        "```bash",
        "market-almanac context refresh        # IMF SDMX API + World Bank Pink Sheet, into your own DATA_DIR",
        "market-almanac context verify         # SHA-256 and structure checks of the snapshot",
        "market-almanac context check-against series_hashes.json   # compare your retrieval with this artefact",
        "```",
        "",
        "A retrieval made later may contain revised values and new months; `check-against` reports which series",
        "match this artefact exactly and which differ (a revision, not an error).",
        "",
        "## Sources",
    ]
    for s in manifest.get("sources", []):
        lic = s.get("licence", {})
        lines += [
            f"- **{s['provider']} / {s['dataset']}**: `{s.get('request')}`; vintage `{s.get('publication_date')}`, "
            f"retrieved `{s.get('retrieved_at')}`; response SHA-256 "
            f"`{s.get('response_sha256') or s.get('workbook_sha256')}`.",
            f"  - Terms: {lic.get('terms')}",
            f"  - Attribution: {lic.get('attribution')}",
            f"  - Position: {lic.get('summary')}",
        ]
    return "\n".join(lines) + "\n"


def build_context_bundle(
    data_dir: Path, mode: str, out_dir: Path, *, snapshot_id: str | None = None, include_unconfirmed: bool = False
) -> dict[str, Any]:
    """Write ``market-almanac-economic-context-<mode>-<stamp>.tar.gz`` honouring the redistribution policy."""
    data_dir = Path(data_dir)
    store = ContextStore(data_dir / "context" / mode)
    sid = snapshot_id or store.latest_id(with_data=True)
    if sid is None:
        raise BundleError(
            f"no economic-context snapshot with data under {data_dir}; run `market-almanac context refresh`"
        )
    problems = store.verify(sid)
    if problems:
        raise BundleError(f"snapshot {sid} does not verify: {problems[0]}")
    snap = ContextSnapshot(store.path(sid))
    manifest = dict(snap.manifest)
    policy = _provider_policy(manifest, include_unconfirmed)
    withheld = sorted(p for p, ok in policy.items() if not ok)

    with tempfile.TemporaryDirectory(prefix="ctx_bundle_") as tmp:
        stage = Path(tmp) / "context" / mode / sid
        stage.mkdir(parents=True)
        series = snap.series_table().reset_index(drop=True)
        obs = snap.observations()
        provider_of = dict(zip(series["series_key"], series["provider"], strict=True))
        allowed = obs["series_key"].map(lambda k: policy.get(str(provider_of.get(k)), False))
        kept = obs[allowed.to_numpy(bool)]
        hashes = series_hashes(obs)
        rejected = json.loads((store.path(sid) / REJECTED_FILE).read_text())
        if withheld:
            rejected = [r | {"value": None} for r in rejected]  # a rejected raw value is still a source value
        (stage / REJECTED_FILE).write_text(json.dumps(rejected, indent=1, sort_keys=True))
        shutil.copyfile(store.path(sid) / DEFS_FILE, stage / DEFS_FILE)
        series.to_parquet(stage / SERIES_FILE, index=False, compression="zstd")
        files = [REJECTED_FILE, DEFS_FILE, SERIES_FILE]
        if len(kept):
            kept.to_parquet(stage / OBS_FILE, index=False, compression="zstd")
            files.append(OBS_FILE)
        included = "full" if not withheld else ("partial" if len(kept) else "none")
        staged_manifest = manifest | {
            "data_included": included,
            "withheld_providers": withheld,
            "files": {f: _sha256(stage / f) for f in files},
            "bundle_policy": (
                "complete artefact, built with include_unconfirmed"
                if include_unconfirmed and withheld == []
                else "per-source: observations are included only where the source's licence record confirms "
                "redistribution; otherwise metadata, citations, retrieval instructions and hashes"
            ),
        }
        (stage / MANIFEST_FILE).write_text(json.dumps(staged_manifest, indent=1, sort_keys=True))
        (stage / SERIES_HASHES).write_text(json.dumps(hashes, indent=0, sort_keys=True))
        (stage / RETRIEVAL).write_text(_retrieval_text(manifest, withheld))
        paths = sorted(p.relative_to(tmp) for p in (Path(tmp) / "context").rglob("*") if p.is_file())
        res = _write_bundle(
            Path(tmp),
            paths,
            mode,
            out_dir,
            fmt=CONTEXT_BUNDLE_FORMAT,
            prefix="market-almanac-economic-context",
            extra={
                "snapshot_id": sid,
                "observation_hash": manifest["observation_hash"],
                "data_included": included,
                "withheld_providers": withheld,
                "series": len(series),
                "observations_included": len(kept),
                "attribution": CONTEXT_ATTRIBUTION,
                "excluded": "HTTP caches, raw provider responses, credentials"
                + ("; observations of " + ", ".join(withheld) if withheld else ""),
                "adaptation_notice": (
                    "Metadata, series tables and hashes are produced by Market Almanac. Index levels, where included, "
                    "are reproduced unchanged; percentage changes shown by the application are computed from them."
                ),
            },
        )
    return res | {"snapshot_id": sid, "data_included": included, "withheld_providers": withheld}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_against(snapshot: ContextSnapshot, reference: dict[str, str]) -> dict[str, list[str]]:
    """Compare a locally retrieved snapshot with a published ``series_hashes.json``."""
    local = series_hashes(snapshot.observations())
    return {
        "identical": sorted(k for k in reference if local.get(k) == reference[k]),
        "different": sorted(k for k in reference if k in local and local[k] != reference[k]),
        "missing_locally": sorted(k for k in reference if k not in local),
        "not_in_reference": sorted(k for k in local if k not in reference),
    }


# --- pinning and installing ---------------------------------------------------------------------------------------


def pinned_release() -> dict[str, Any] | None:
    return json.loads(RELEASE_FILE.read_text()) if RELEASE_FILE.exists() else None


def resolve_source(settings: Any, source: str | None = None, sha256: str | None = None) -> tuple[str, str]:
    rel = pinned_release() or {}
    url = source or settings.context_bundle_url or rel.get("url")
    digest = (
        sha256
        or settings.context_bundle_sha256
        or (rel.get("sha256") if not source and not settings.context_bundle_url else None)
    )
    if not url:
        raise BundleError("no economic-context artefact configured: set CONTEXT_BUNDLE_URL or pin a release")
    if not digest:
        raise BundleError("a SHA-256 is required to install the artefact (CONTEXT_BUNDLE_SHA256)")
    return str(url), str(digest)


def is_installed(settings: Any) -> bool:
    """True when a snapshot with observations is present. A metadata-only snapshot does not count: the engine then
    reports the context as unavailable instead of pretending to have data."""
    try:
        return ContextStore.for_settings(settings).latest_id(with_data=True) is not None
    except ContextStoreError:
        return False


def install_context(settings: Any, source: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    if settings.market_almanac_mode.value != "live":
        raise BundleError("the economic-context artefact is installed in live mode only")
    url, digest = resolve_source(settings, source, sha256)
    res = install_bundle(url, Path(settings.data_dir), digest)
    if res.get("format") != CONTEXT_BUNDLE_FORMAT:
        raise BundleError(f"{url} is not an economic-context artefact (format {res.get('format')!r})")
    store = ContextStore.for_settings(settings)
    sid = store.latest_id()
    if sid is None:
        raise BundleError("the installed artefact holds no snapshot")
    problems = store.verify(sid)
    if problems:
        raise BundleError(f"installed snapshot {sid} does not verify: {problems[0]}")
    return res | {"snapshot_id": sid, "has_data": is_installed(settings)}
