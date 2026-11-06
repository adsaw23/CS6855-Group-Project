#!/usr/bin/env python3
"""Public numeric checks on explicitly labelled NetworkX fixtures, WITHOUT an LLM.

These are integration tests, not official answers_public.json or planner accuracy.
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import networkx as nx
from graphkit.graph import GraphStore
from orchestrator.registry import Registry
from orchestrator import utilities
from orchestrator.queries import read_raw
from scripts.evaluate import score


def fixture_store():
    store = GraphStore()
    karate = nx.relabel_nodes(nx.karate_club_graph(), {n: f"m{n+1}" for n in range(34)})
    for n in karate:
        karate.nodes[n]["label"] = f"Member {n[1:]}" + (
            " (instructor)" if n == "m1" else " (administrator)" if n == "m34" else ""
        )
    lesmis = nx.les_miserables_graph()
    mapping = {n: f"c{i:02}" for i, n in enumerate(sorted(lesmis), 1)}
    for n in lesmis:
        lesmis.nodes[n]["label"] = n
    lesmis = nx.relabel_nodes(lesmis, mapping)
    store.add("karate", karate, "NetworkX built-in TEST FIXTURE, not official dataset")
    store.add("lesmis", lesmis, "NetworkX built-in TEST FIXTURE, alphabetical c01-c77 identifiers")
    return store


def run_checks():
    registry = Registry(ROOT / "registry/tools")
    records = []
    expected = {r["Query ID"]: r for r in read_raw(ROOT / "CS6855_Public_Query_Set (1).xlsx")}
    target = ROOT / "evaluation/fixture_traces"
    target.mkdir(parents=True, exist_ok=True)
    for qid in ["q08", "q09", "q10", "q11", "q12", "q17", "q19", "q20", "q21", "q22"]:
        store = fixture_store()
        trace = []

        def call(name, graph_id, **params):
            args = {"graph_id": graph_id, **params}
            output = (
                utilities.FUNCTIONS[name](store, **args)
                if name in utilities.FUNCTIONS
                else registry.execute(name, store, args)
            )
            trace.append({"event": "tool_call", "name": name, "arguments": args, "output": output})
            if output["status"] != "ok":
                raise AssertionError(output)
            return output

        if qid == "q08":
            value = [
                x["id"]
                for x in call("betweenness_centrality", "karate", top_k=3, weighted=False)["result"]
            ]
        elif qid == "q09":
            value = [
                x["id"]
                for x in call("articulation_points_bridges", "karate", top_k=100)["result"][
                    "articulation_points"
                ]
            ]
        elif qid == "q10":
            value = call("maximal_cliques", "karate")["result"]["max_size"]
        elif qid == "q11":
            sub = call("project_graph", "karate", mode="unit_weights")["result_graph_id"]
            value = call("max_flow_min_cut", sub, source="m1", sink="m34")["result"]["max_flow"]
        elif qid == "q12":
            value = call("node_similarity", "lesmis", node_a="c74", node_b="c40")["result"][
                "jaccard"
            ]
        elif qid == "q17":
            sub = call("ego_network", "karate", node="m1")["result_graph_id"]
            value = next(
                x["id"]
                for x in call("degree_centrality", sub, top_k=100)["result"]
                if x["id"] != "m1"
            )
        elif qid == "q19":
            sub = call("girvan_newman", "karate", num_communities=2, weighted=False)[
                "result_graph_id"
            ]
            value = call("pagerank", sub, weighted=False, top_k=1)["result"][0]["id"]
        elif qid == "q20":
            sub = call("k_core", "karate")["result_graph_id"]
            value = call("clustering_coefficient", sub, weighted=False)["result"][
                "average_clustering"
            ]
        elif qid == "q21":
            sub = call("ego_network", "lesmis", node="c74")["result_graph_id"]
            value = next(
                x["id"]
                for x in call("betweenness_centrality", sub, weighted=False, top_k=100)["result"]
                if x["id"] != "c74"
            )
        elif qid == "q22":
            sub = call("ego_network", "lesmis", node="c40")["result_graph_id"]
            value = call("motif_count", sub, motif="triangle")["result"]["triangles"]
        answer = {
            "query_id": qid,
            "status": "answered",
            "answer": {"type": expected[qid]["Answer type"], "value": value},
        }
        passed, reason = score(expected[qid], answer)
        records.append({**answer, "passed": passed, "reason": reason, "tool_calls": len(trace)})
        (target / (qid + ".jsonl")).write_text(
            "\n".join(
                json.dumps(t)
                for t in [
                    {
                        "event": "fixture_only",
                        "description": "Manual tool-chain test, no LLM; NetworkX built-in graph.",
                    },
                    *trace,
                    {"event": "test_result", "result": records[-1]},
                ]
            )
            + "\n"
        )
    report = {
        "scope": "Only tool/executor correctness on built-in fixtures, NOT full public-set or LLM accuracy",
        "networkx_version": nx.__version__,
        "passed": sum(r["passed"] for r in records),
        "total": len(records),
        "results": records,
    }
    (ROOT / "evaluation/public_fixture_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    report = run_checks()
    print(json.dumps(report, indent=2))
    raise SystemExit(report["passed"] != report["total"])
