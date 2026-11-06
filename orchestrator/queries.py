"""JSON/JSONL/CSV/XLSX input. Expected answers are never sent to the planner."""

import csv
import json
from pathlib import Path
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

# Accepted column names, compared after lower-casing and turning spaces/hyphens into "_".
ID_KEYS = ("query_id", "queryid", "id", "qid", "question_id")
QUESTION_KEYS = ("question", "query", "question_text", "text", "prompt")
GRAPH_KEYS = ("graph_id", "graph", "graph_name", "dataset")


def _key(name):
    return re.sub(r"[\s\-]+", "_", str(name).strip().casefold())


def _pick(row, keys):
    normalised = {_key(k): v for k, v in row.items()}
    for key in keys:
        if key in normalised:
            return normalised[key]
    return None


def _warn(message):
    print(f"warning: {message}", file=sys.stderr)


def _first_sheet(z):
    """Path of the first worksheet in workbook order, not just sheet1.xml."""
    try:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rel_id = workbook.find("s:sheets/s:sheet", NS).get(REL_NS)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall("r:Relationship", PKG_NS):
            if rel.get("Id") == rel_id:
                target = rel.get("Target")
                return target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                    posixpath.join("xl", target)
                )
    except (KeyError, AttributeError, ET.ParseError):
        pass
    return "xl/worksheets/sheet1.xml"


def spreadsheet_rows(path):
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = [
                "".join(t.text or "" for t in item.findall(".//s:t", NS))
                for item in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si", NS)
            ]
        root = ET.fromstring(z.read(_first_sheet(z)))
        rows = []
        for row in root.findall(".//s:row", NS):
            values = {}
            for cell in row:
                col = re.sub(r"\d", "", cell.get("r", ""))
                value = cell.find("s:v", NS)
                text = (
                    value.text
                    if value is not None
                    else "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                )
                if cell.get("t") == "s":
                    text = strings[int(text)]
                values[col] = (text or "").strip()
            rows.append(values)
    # The header is the first row with a query-ID column; titles above it are ignored.
    for index, row in enumerate(rows):
        id_cols = [c for c, v in row.items() if _key(v) in ID_KEYS]
        if id_cols:
            headers, id_col = row, id_cols[0]
            break
    else:
        raise ValueError(f"{path}: no query ID column found")
    # Data rows carry a single-token ID; notes or blank lines under the table are skipped.
    return [
        {headers[col]: r.get(col, "") for col in headers}
        for r in rows[index + 1 :]
        if re.fullmatch(r"\S+", r.get(id_col, ""))
    ]


def read_raw(path):
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        return spreadsheet_rows(path)
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    raw = json.loads(path.read_text())
    return raw["queries"] if isinstance(raw, dict) else raw


def read_queries(path):
    """Normalise rows; a bad row is skipped with a warning instead of aborting the run."""
    result, seen = [], set()
    for number, row in enumerate(read_raw(path), 1):
        if not isinstance(row, dict):
            _warn(f"row {number} is not an object; skipped")
            continue
        qid = _pick(row, ID_KEYS)
        if isinstance(qid, bool) or not isinstance(qid, (str, int)) or not str(qid).strip():
            _warn(f"row {number} has no query ID; skipped")
            continue
        qid = str(qid).strip()
        if qid in seen:
            _warn(f"duplicate query ID {qid!r} in row {number}; skipped")
            continue
        seen.add(qid)
        question = _pick(row, QUESTION_KEYS)
        question = question.strip() if isinstance(question, str) else ""
        graph = _pick(row, GRAPH_KEYS)
        graph = graph.strip() if isinstance(graph, str) else None
        if graph in ("", "(none)", "none", "null", "-", "—"):
            graph = None
        result.append({"query_id": qid, "graph_id": graph, "question": question})
    return result
