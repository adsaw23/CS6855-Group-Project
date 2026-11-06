#!/usr/bin/env python3
"""Score public outputs independently of the agent; never imported by the planner."""

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orchestrator.queries import read_raw, read_queries
from graphkit.graph import GraphStore


def expected_value(row):
    value = row["Expected answer"]
    kind = row["Answer type"]
    if kind == "number":
        return float(value)
    if kind == "boolean":
        return value.strip().lower() == "true"
    if kind == "node_list":
        return [x.strip() for x in value.split(",")]
    if kind == "path":
        return [x.strip() for x in value.replace("→", "->").split("->")]
    return value


def score(row, answer, store=None):
    if answer is None:
        return False, "Missing answer"
    if answer["status"] != row["Expected status"]:
        return False, "Status differs"
    if answer["status"] != "answered":
        return True, "Correct status"
    actual = answer.get("answer", {})
    kind = row["Answer type"]
    expected = expected_value(row)
    if actual.get("type") != kind:
        return False, "Answer type differs"
    value = actual.get("value")
    if kind == "number":
        correct = (
            type(value) in (int, float)
            and math.isfinite(value)
            and math.isclose(value, expected, rel_tol=0.001, abs_tol=1e-9)
        )
    elif kind == "boolean":
        correct = type(value) is bool and value == expected
    elif kind == "node_list":
        if "prerequisite" in row.get("Notes", "").lower():
            if store is None:
                return None, "Needs official graph to validate alternative topological orders"
            g = store.get(row["Graph"])._graph
            pos = {v: i for i, v in enumerate(value)}
            correct = (
                len(value) == len(g)
                and set(value) == set(g)
                and all(pos[u] < pos[v] for u, v in g.edges)
            )
        elif "order matters" in row.get("Notes", "").lower():
            correct = value == expected
        else:
            correct = isinstance(value, list) and set(value) == set(expected)
    else:
        correct = value == expected
    return correct, "Match" if correct else f"Expected {expected!r}, got {value!r}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--expected", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--data")
    p.add_argument(
        "--queries", help="Explicit query subset to score; omitted means the entire answer key"
    )
    p.add_argument("--out", default="evaluation/public_score.json")
    a = p.parse_args()
    rows = read_raw(a.expected)
    answers = {v["query_id"]: v for v in json.loads(Path(a.answers).read_text())}
    store = GraphStore.from_directory(a.data) if a.data else None
    if a.queries:
        wanted = {q["query_id"] for q in read_queries(a.queries)}
        unknown = wanted - {r["Query ID"] for r in rows}
        if unknown:
            raise ValueError(f"Queries absent from answer key: {sorted(unknown)}")
        rows = [r for r in rows if r["Query ID"] in wanted]
    results = []
    for row in rows:
        passed, reason = score(row, answers.get(row["Query ID"]), store)
        results.append({"query_id": row["Query ID"], "passed": passed, "reason": reason})
    report = {
        "correct": sum(r["passed"] is True for r in results),
        "total": len(results),
        "ungraded": sum(r["passed"] is None for r in results),
        "results": results,
    }
    target = Path(a.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))


if __name__ == "__main__":
    main()
