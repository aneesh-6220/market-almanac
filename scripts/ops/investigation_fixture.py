"""Regenerate the web client's investigation fixture from the synthetic demo (offline, local SQLite).

    make demo
    uv run python scripts/ops/investigation_fixture.py apps/web/src/lib/__fixtures__/investigation-demo.json

The web unit tests parse this real API output with the client's schemas, so drift is caught without a browser.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def main(out: Path) -> None:
    os.environ.update(
        MARKET_ALMANAC_MODE="demo",
        DATABASE_URL="sqlite:///./data/market-almanac.db",
        API_RATE_LIMIT_PER_MINUTE="100000",
    )
    from fastapi.testclient import TestClient

    from market_almanac_api.main import create_app

    c = TestClient(create_app())
    page = c.get("/api/v1/shocks", params={"limit": 2}).json()
    it = page["items"][0]
    d = c.get(f"/api/v1/investigations/{it['series_id']}", params={"event": it["peak"]}).json()

    def keep(rows: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
        return rows[:n] + [r for r in rows if r.get("elevated") is None][:1]

    d["signals"] = d["signals"][:4] + [s for s in d["signals"] if s["price"] is None][:1]
    d["peers"]["rows"] = keep(d["peers"]["rows"])
    d["breadth"]["rows"] = keep(d["breadth"]["rows"])
    d["peers"]["index"]["rows"] = d["peers"]["index"]["rows"][:3]
    page["items"] = page["items"][:2]
    out.write_text(json.dumps({"shocks": page, "investigation": d}, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
