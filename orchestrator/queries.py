"""JSON/JSONL/CSV/XLSX input. Expected answers are never sent to the planner."""

import csv
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET


def spreadsheet_rows(path):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = [
                "".join(t.text or "" for t in item.findall(".//s:t", ns))
                for item in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si", ns)
            ]
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in root.findall(".//s:row", ns):
            values = {}
            for cell in row:
                col = re.sub(r"\d", "", cell.get("r", ""))
                value = cell.find("s:v", ns)
                text = (
                    value.text
                    if value is not None
                    else "".join(t.text or "" for t in cell.findall(".//s:t", ns))
                )
                if cell.get("t") == "s":
                    text = strings[int(text)]
                values[col] = text
            rows.append(values)
        headers = rows[0]
        return [
            {headers[col]: row.get(col, "") for col in headers}
            for row in rows[1:]
            if re.fullmatch(r"q\d+", row.get("A", ""))
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
    result, seen = [], set()
    for row in read_raw(path):
        qid = row.get("query_id", row.get("Query ID"))
        if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", qid):
            raise ValueError("query_id must contain only letters, digits, _ or -")
        if qid in seen:
            raise ValueError(f"Duplicate query ID: {qid}")
        seen.add(qid)
        question = row.get("question", row.get("Question"))
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{qid}: missing question")
        graph = row.get("graph_id", row.get("graph", row.get("Graph")))
        if graph in ("", "(none)"):
            graph = None
        if graph is not None and not isinstance(graph, str):
            raise ValueError(f"{qid}: graph_id must be a string or null")
        result.append({"query_id": qid, "graph_id": graph, "question": question})
    return result
