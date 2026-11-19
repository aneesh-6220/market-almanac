"""The pinned, hash-verified data-only price artefact and how a deployment installs it.

The release descriptor ``prices_release.json`` is committed with the code. It names the artefact (a
GitHub release asset), its SHA-256 and what it contains, so a given commit always installs exactly the
data it was tested with. Environment variables (``GLOBAL_PRICES_BUNDLE_URL`` / ``..._SHA256``) override
it for operators who host the artefact elsewhere.

Installation is safe by construction (see :mod:`market_almanac.data.public_bundle`): the archive hash and
every file's hash are verified before anything is written; files are written atomically with the
partition manifest last, so a country is never visible half-installed; an installed file that differs from
the artefact is never overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from market_almanac.data.public_bundle import BundleError, install_bundle
from market_almanac.globaldata.prices import GlobalPrices

RELEASE_FILE = Path(__file__).with_name("prices_release.json")


def pinned_release() -> dict[str, Any] | None:
    return json.loads(RELEASE_FILE.read_text()) if RELEASE_FILE.exists() else None


def resolve_source(settings: Any, source: str | None = None, sha256: str | None = None) -> tuple[str, str]:
    """(url-or-path, sha256): explicit arguments, then settings, then the pinned release. SHA-256 is mandatory."""
    rel = pinned_release() or {}
    url = source or settings.global_prices_bundle_url or rel.get("url")
    digest = (
        sha256
        or settings.global_prices_bundle_sha256
        or (rel.get("sha256") if not source and not settings.global_prices_bundle_url else None)
    )
    if not url:
        raise BundleError("no price artefact configured: set GLOBAL_PRICES_BUNDLE_URL or pin a release")
    if not digest:
        raise BundleError("a SHA-256 is required to install a price artefact (GLOBAL_PRICES_BUNDLE_SHA256)")
    return str(url), str(digest)


def is_installed(settings: Any) -> bool:
    """True when every country's newest partition is present and the catalog and the price-shock episode table were
    built from exactly those. A volume that holds an older artefact (prices and catalog but no episodes) is therefore
    not "installed": the install is idempotent and adds what is missing instead of leaving the investigator without
    its discovery table."""
    gp = GlobalPrices(settings)
    if not (gp.layout() == "partition" and gp.available() and not gp.stale_countries()):
        return False
    from market_almanac.globaldata.shocks import SHOCK_CATALOG, load_manifest, stale_countries

    manifest = load_manifest(gp.public_dir)
    if manifest is None or not (gp.public_dir / SHOCK_CATALOG).is_file():
        return False
    sources = gp.sources()[0]
    return not stale_countries(manifest, {c: s.snapshot_id for c, s in sources.items()})


def install_prices(settings: Any, source: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    """Download (if needed), verify and install the artefact, then confirm the installed data are consistent."""
    if settings.market_almanac_mode.value != "live":
        raise BundleError("the global price artefact is installed in live mode only")
    url, digest = resolve_source(settings, source, sha256)
    res = install_bundle(url, Path(settings.data_dir), digest)
    if res.get("format") != "market-almanac-global-prices-1":
        raise BundleError(f"{url} is not a global price artefact (format {res.get('format')!r})")
    gp = GlobalPrices(settings)
    gp.invalidate()
    stale = gp.stale_countries()
    if not gp.available() or stale:
        raise BundleError(f"installed price data are inconsistent with their catalog (stale: {stale[:5]})")
    return res | {"countries": len(gp.sources()[0])}
