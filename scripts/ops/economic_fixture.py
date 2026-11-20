"""Regenerate the web client's economic-context fixture from a SYNTHETIC world (offline; no network, no database).

    uv run python scripts/ops/economic_fixture.py apps/web/src/lib/__fixtures__/economic-context.json

Synthetic prices plus a synthetic IMF/World Bank world served by the test double that the ingestion tests use, run
through the real refresh, store, engine, evidence layer and API. Nothing here is IMF or World Bank data, so the file
can be committed. The web unit tests parse it with the client's schemas.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(out: Path) -> None:
    from tests import context_support as cs
    from tests.global_support import build_catalog_for, deployment, obs_rows, write_country

    root = Path(tempfile.mkdtemp())
    data = root / "data"
    price = {i: 100.0 * 1.003**i * (1.55 if i >= 77 else 1.0) for i in range(105)}
    for iso, cur in (("KEN", "KES"), ("NER", "XOF")):
        write_country(
            data,
            iso,
            obs_rows(
                country=iso,
                market=("1", "Alpha", 1.0, 36.0),
                commodity=("10", "Rice (imported)"),
                currency=cur,
                start="2018-01-01",
                months=105,
                prices=price,
            ),
        )
    build_catalog_for(data, ["KEN", "NER"])

    def fetch(c: Any, iso: str) -> dict[str, Any]:
        items = c.get(f"/api/v1/global/countries/{iso}/series", params={"limit": 1}).json()["items"]
        d = c.get(f"/api/v1/investigations/{items[0]['series_id']}", params={"event": "2024-09"}).json()
        return {
            "series_id": items[0]["series_id"],
            "economic": d["context"]["economic"],
            "evidence": d["evidence"].get("economic"),
        }

    result: dict[str, Any] = {}
    with deployment(data, root / "db0") as c:
        result["not_installed"] = fetch(c, "KEN")
    snap = cs.build_snapshot(root / "ctx")
    shutil.copytree(snap.dir, data / "context" / "live" / snap.snapshot_id)
    with deployment(data, root / "db1") as c:
        result["full"] = fetch(c, "KEN")
        result["missing_food"] = fetch(c, "NER")
    out.write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
