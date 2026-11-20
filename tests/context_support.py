"""Synthetic sources for the economic-context tests: SDMX messages, a Pink Sheet workbook and a scripted HTTP server.

Everything here is **synthetic**: no IMF or World Bank observation is committed to the repository (their redistribution
terms are not confirmed). The series are constructed to reproduce the *structures* real data showed during source
verification, each one named after the behaviour it pins down:

* ``KEN``  complete: headline CPI, food CPI and exchange rates, with an ordinary price path;
* ``NER``  headline CPI and exchange rates; the food-CPI series exists but every observation is empty;
* ``LBY``  a CPI rebase that was not spliced (the level drops by ~70% at a reference-period change);
* ``ZWE``  an exchange-rate value dated in a future month, and a CPI month reported twice;
* ``SEN``  a currency-union member (XOF) with a flat per-USD path of its own.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import httpx

from market_almanac.context.reference import benchmark_table

NOW = "2026-11-20T00:00:00+00:00"
START, END = "2018-01", "2026-09"
PINK_PAGE = (
    '<html><a href="https://thedocs.worldbank.org/en/doc/abc-123/related/CMO-Historical-Data-Monthly.xlsx">x</a></html>'
)


def months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def tp(period: str) -> str:
    return f"{period[:4]}-M{period[5:]}"


def path(
    growth: float, *, start: float = 100.0, steps: dict[str, float] | None = None, span: tuple[str, str] = (START, END)
) -> dict[str, float]:
    """A level that grows ``growth`` per month, multiplied by ``steps[month]`` from that month on."""
    out: dict[str, float] = {}
    level = start
    for m in months(*span):
        level *= 1 + growth
        if steps and m in steps:
            level *= steps[m]
        out[m] = round(level, 6)
    return out


Obs = tuple[str, float | None, dict[str, str]]


def series(
    country: str,
    values: dict[str, float | None],
    *,
    ref: str = "2010",
    extra: dict[str, str] | None = None,
    obs_extra: list[Obs] | None = None,
    ref_by_month: dict[str, str] | None = None,
) -> dict[str, Any]:
    obs: list[Obs] = [(m, v, {"REFERENCE_PERIOD": (ref_by_month or {}).get(m, ref)}) for m, v in values.items()]
    obs += obs_extra or []
    return {
        "attrs": {"COUNTRY": country, "FREQUENCY": "M", "COMMON_REFERENCE_PERIOD": ref, **(extra or {})},
        "obs": obs,
    }


def sdmx_xml(flow: str, items: list[dict[str, Any]], publication: str = "2026-11-19T07:43:56Z") -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<message:StructureSpecificData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
        'xmlns:ss="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/structurespecific">',
        f'<message:Header><message:Structure><Ref agencyID="IMF.STA" id="{flow}" version="5.0.0"/></message:Structure>'
        "</message:Header>",
        f'<message:DataSet PUBLICATION_DATE="{publication}" UPDATE_DATE="{publication}" '
        'SUGGESTED_CITATION="International Monetary Fund (synthetic test dataset)">',
    ]
    for s in items:
        attrs = " ".join(f"{k}={quoteattr(str(v))}" for k, v in s["attrs"].items())
        out.append(f"<Series {attrs}>")
        for period, value, extra in s["obs"]:
            a = f"TIME_PERIOD={quoteattr(tp(period) if re.fullmatch(r'\d{4}-\d{2}', period) else period)}"
            if value is not None:
                a += f' OBS_VALUE="{value}"'
            a += "".join(f" {k}={quoteattr(v)}" for k, v in extra.items())
            out.append(f"<Obs {a}/>")
        out.append("</Series>")
    out += ["</message:DataSet>", "</message:StructureSpecificData>"]
    return "\n".join(out)


def world() -> dict[str, list[dict[str, Any]]]:
    """concept name -> series specs (see the module docstring)."""
    ms = months(START, END)
    ken_cpi = path(0.004)
    ken_food = path(0.006, steps={"2024-06": 1.08})
    ner_cpi = path(0.003, steps={"2024-06": 1.03})
    lby_levels = path(0.002, steps={"2025-01": 0.30}, span=(START, "2025-06"))
    lby_ref = {m: ("2010" if m < "2025-01" else "2024") for m in lby_levels}
    zwe_cpi = path(0.01, span=(START, "2026-06"))
    sen_cpi = path(0.002)
    ken_fx = path(0.002, start=100.0)
    ner_fx = path(0.0, start=600.0, span=(START, END))
    sen_fx = path(0.0, start=600.0, span=(START, END))
    zwe_fx = path(0.03, start=1.0, span=(START, "2026-06"))
    zwe_fx["2027-03"] = 9.9  # future-dated: validation must refuse it
    zwe_dup = [("2020-05", 123456.0, {"REFERENCE_PERIOD": "2010"})]  # same month reported twice
    return {
        "cpi_headline": [
            series("KEN", ken_cpi),
            series("NER", ner_cpi, ref="2014"),
            series("LBY", lby_levels, ref="2010", ref_by_month=lby_ref),
            series("ZWE", zwe_cpi, obs_extra=zwe_dup),
            series("SEN", sen_cpi, ref="2014"),
        ],
        "cpi_food": [
            series("KEN", ken_food),
            series("NER", {m: None for m in ms}, ref="2014"),
            series("SEN", path(0.003), ref="2014"),
        ],
        "fx_period_avg": [
            series("KEN", ken_fx, ref=""),
            series("NER", ner_fx, ref=""),
            series("ZWE", zwe_fx, ref=""),
            series("SEN", sen_fx, ref=""),
        ],
        "fx_end_period": [series("KEN", ken_fx, ref=""), series("NER", ner_fx, ref="")],
    }


# --- Pink Sheet workbook ------------------------------------------------------------------------------------------

UNIT_CODE = {"USD per metric ton": "($/mt)", "USD per kilogram": "($/kg)", "USD per barrel": "($/bbl)"}


def _col(i: int) -> str:
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(dest: Path, sheets: dict[str, list[list[Any]]]) -> Path:
    """Write a minimal .xlsx (inline strings and numbers). ``None`` cells are left empty."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        sheet_xml = "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1))
        z.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>{sheet_xml}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>' for i in range(1, len(sheets) + 1)
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
        )
        for i, rows in enumerate(sheets.values(), 1):
            body = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, v in enumerate(row, 1):
                    if v is None:
                        continue
                    ref = f"{_col(c)}{r}"
                    if isinstance(v, int | float):
                        cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                    else:
                        t = str(v).replace("&", "&amp;").replace("<", "&lt;")
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{t}</t></is></c>')
                body.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(
                f"xl/worksheets/sheet{i}.xml",
                f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>',
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(buf.getvalue())
    return dest


def pink_rows(
    *,
    overrides: dict[tuple[str, str], Any] | None = None,
    end: str = END,
    sorghum_end: str | None = "2020-08",
    unit_override: dict[str, str] | None = None,
    drop: set[str] | None = None,
) -> dict[str, list[list[Any]]]:
    """Sheets of a Pink-Sheet-shaped workbook for every mapped benchmark. ``overrides[(benchmark_id, 'YYYY-MM')]``
    replaces a cell (use ``"#VALUE!"`` or ``0``); ``sorghum_end`` stops that series (the real one was discontinued)."""
    table = benchmark_table()["benchmarks"]
    ids = [b for b in table if b not in (drop or set())]
    header: list[Any] = [None, *[table[b]["pink_name"] + ("*" if b == "rice_thai_5" else "") for b in ids]]
    units: list[Any] = [None, *[(unit_override or {}).get(b, UNIT_CODE[table[b]["unit"]]) for b in ids]]
    rows: list[list[Any]] = [
        ["World Bank Commodity Price Data (The Pink Sheet)"],
        ["Updated on November 3, 2026"],
        [],
        header,
        units,
    ]
    for k, m in enumerate(months("2010-01", end)):
        row: list[Any] = [f"{m[:4]}M{m[5:]}"]
        for j, b in enumerate(ids):
            v: Any = round(100 + 3 * j + 0.5 * k, 2)
            if b == "sorghum" and sorghum_end and m > sorghum_end:
                v = None
            if overrides and (b, m) in overrides:
                v = overrides[(b, m)]
            row.append(v)
        rows.append(row)
    desc: list[list[Any]] = [["Commodity", "Description", "Sources"]]
    for b in table:
        desc.append(
            [None, f"{table[b]['description_prefix']} (synthetic test description)", f"Synthetic source for {b}"]
        )
    return {"Monthly Prices": rows, "Description": desc}


def pink_workbook(dest: Path, **kw: Any) -> Path:
    return write_xlsx(dest, pink_rows(**kw))


# --- scripted HTTP server -----------------------------------------------------------------------------------------


def handler(
    world_: dict[str, list[dict[str, Any]]],
    workbook: Path,
    *,
    publication: str = "2026-11-19T07:43:56Z",
    fail_first: dict[str, int] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """An httpx handler answering the four IMF bulk requests, the Commodity Markets page and the workbook."""
    failures = dict(fail_first or {})
    routes = {
        ".CPI._T.IX.M": ("CPI", "cpi_headline"),
        ".CPI.CP01.IX.M": ("CPI", "cpi_food"),
        ".XDC_USD.PA_RT.M": ("ER", "fx_period_avg"),
        ".XDC_USD.EOP_RT.M": ("ER", "fx_end_period"),
    }

    def serve(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        for key, (flow, concept) in routes.items():
            if req.url.path.endswith(key):
                if failures.get(concept, 0) > 0:
                    failures[concept] -= 1
                    return httpx.Response(503, text="busy")
                return httpx.Response(200, text=sdmx_xml(flow, world_[concept], publication))
        if "commodity-markets" in url:
            return httpx.Response(200, text=PINK_PAGE)
        if url.endswith("CMO-Historical-Data-Monthly.xlsx"):
            return httpx.Response(200, content=workbook.read_bytes())
        return httpx.Response(404, text="not found")

    return serve
