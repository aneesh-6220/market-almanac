"""A minimal, dependency-free reader for the cells of an ``.xlsx`` workbook (strings and numbers only).

The World Bank Pink Sheet is published as a spreadsheet. Reading it needs only the OOXML parts that hold cell
values, so this module uses the standard library (``zipfile`` and ``xml``) instead of adding a spreadsheet package
to the API image. It reads values as the file stores them: no formulas are evaluated, no dates are guessed (a date
stored as a number comes back as that number's text), and nothing is executed.

Safety: only the needed members are read, each is size-limited (a hostile archive cannot expand without bound), and
no external references are followed.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_MEMBER_BYTES = 200 * 1024**2
_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


class XlsxError(ValueError):
    """The workbook is not a readable .xlsx or lacks an expected part."""


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = z.getinfo(name)
    except KeyError as exc:
        raise XlsxError(f"workbook has no part {name!r}") from exc
    if info.file_size > MAX_MEMBER_BYTES:
        raise XlsxError(f"part {name!r} is larger than {MAX_MEMBER_BYTES} bytes")
    return z.read(info)


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{_NS_MAIN}t"))


def read_workbook(path: Path) -> dict[str, dict[int, dict[str, str]]]:
    """``{sheet name: {row number: {column letters: cell text}}}`` for every worksheet (empty cells are absent)."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise XlsxError(f"{path.name} is not a valid .xlsx (zip) file") from exc
    with z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(_read(z, "xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.iter(f"{_NS_MAIN}si")]
        wb = ET.fromstring(_read(z, "xl/workbook.xml"))
        rels = ET.fromstring(_read(z, "xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels.iter(f"{_NS_PKG_REL}Relationship")}
        out: dict[str, dict[int, dict[str, str]]] = {}
        for sh in wb.iter(f"{_NS_MAIN}sheet"):
            name = sh.attrib["name"]
            target = targets.get(sh.attrib.get(f"{_NS_REL}id", ""))
            if target is None:
                continue
            part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            rows: dict[int, dict[str, str]] = {}
            for row in ET.fromstring(_read(z, part)).iter(f"{_NS_MAIN}row"):
                cells: dict[str, str] = {}
                for c in row.iter(f"{_NS_MAIN}c"):
                    m = _CELL_RE.match(c.attrib.get("r", ""))
                    if not m:
                        continue
                    t = c.attrib.get("t")
                    if t == "inlineStr":
                        val = _text(c)
                    else:
                        v = c.find(f"{_NS_MAIN}v")
                        if v is None or v.text is None:
                            continue
                        val = shared[int(v.text)] if t == "s" else v.text
                    cells[m.group(1)] = val
                if cells and row.attrib.get("r", "").isdigit():
                    rows[int(row.attrib["r"])] = cells
            out[name] = rows
        return out


def column_index(letters: str) -> int:
    """Spreadsheet column letters to a 1-based number (A=1, Z=26, AA=27)."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n
