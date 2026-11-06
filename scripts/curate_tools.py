#!/usr/bin/env python3
"""Test every submitted implementation; copy only passing selections unchanged.

The report differentiates exact oracle comparisons from structural invariants.
An unrecognised output schema fails selection; that alone is not an algorithm bug.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import networkx as nx
from graphkit.graph import GraphStore
from orchestrator.registry import load_module, deadline


def near(actual, expected, tolerance=1e-5):
    if not isinstance(actual, (int, float)) or abs(actual - expected) > max(
        tolerance, abs(expected) * 0.0005
    ):
        raise AssertionError(f"Expected {expected}, got {actual}")


def field(result, *names):
    if isinstance(result, dict):
        for name in names:
            if name in result:
                return result[name]
    raise AssertionError("Output missing structured field: " + "/".join(names))


def entries(result):
    if isinstance(result, list):
        return result
    for key in ("ranking", "top_items", "nodes", "scores", "rankings", "top_nodes"):
        if isinstance(result.get(key), list):
            return result[key]
    if "id" in result:
        return [result]
    raise AssertionError("Output has no recognised ranking")


def ids(values):
    return [v["id"] if isinstance(v, dict) else v for v in values]


def fixture(kind):
    g = nx.Graph()
    g.add_weighted_edges_from(
        [("a", "b", 2), ("b", "c", 3), ("c", "d", 1), ("b", "d", 4), ("d", "e", 2)]
    )
    if kind == "disconnected":
        g.add_node("f")
    if kind == "directed":
        g = nx.DiGraph(g)
        g.remove_edge("e", "d")
        g.remove_edge("c", "b")
        g.add_node("f")
    if kind == "bipartite":
        g = nx.Graph([("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")])
    if kind == "hits":
        g = nx.DiGraph([("a", "b"), ("b", "c"), ("c", "d"), ("b", "d"), ("d", "e")])
    if kind == "dag":
        g = nx.DiGraph([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e")])
    if kind == "karate":
        g = nx.relabel_nodes(nx.karate_club_graph(), {n: f"m{n+1}" for n in range(34)})
    return g


def parameters(m, g):
    props = m["parameters"]["properties"]
    name = m["name"]
    nodes = list(g)
    first, last = nodes[0], nodes[-1]
    args = {"graph_id": "fixture"}
    for key in props:
        if key == "top_k":
            args[key] = 100
        if key in ("weighted", "use_weights"):
            args[key] = False
        if key in ("source", "node_a", "seed_node"):
            args[key] = first
        if key in ("target", "sink", "node_b"):
            args[key] = last
        if key == "node" and (
            key in m["parameters"].get("required", [])
            or name
            in (
                "ego_network",
                "k_hop_neighborhood",
                "node_embedding_similarity",
                "personalized_pagerank",
            )
        ):
            args[key] = first
        if key == "num_communities":
            args[key] = 2
        if key == "max_iter":
            args[key] = min(1000, props[key].get("maximum", 1000))
        if key == "tol":
            args[key] = 1e-10
    return args


def oracle(name, g, r, store, output, args):
    # All reference centralities are explicitly unweighted.
    if name in (
        "degree_centrality",
        "betweenness_centrality",
        "closeness_centrality",
        "pagerank",
        "personalized_pagerank",
    ):
        if name == "degree_centrality":
            expected = nx.degree_centrality(g)
        elif name == "betweenness_centrality":
            expected = nx.betweenness_centrality(g, weight=None)
        elif name == "closeness_centrality":
            expected = nx.closeness_centrality(g, wf_improved=True)
        elif name == "pagerank":
            expected = nx.pagerank(g, weight=None, tol=1e-12, max_iter=2000)
        else:
            source = args.get("source", args.get("seed_node", args.get("node")))
            expected = nx.pagerank(
                g,
                weight=None,
                personalization={v: float(v == source) for v in g},
                tol=1e-12,
                max_iter=2000,
            )
        rows = entries(r)
        required = {
            v for v in g if name != "personalized_pagerank" or (v != source and expected[v] > 1e-8)
        }
        if not required.issubset({row["id"] for row in rows}):
            raise AssertionError("Incomplete ranking on small fixture")
        for row in rows:
            near(field(row, "score", "closeness", "centrality", "pagerank"), expected[row["id"]])
        scores = [expected[row["id"]] for row in rows]
        if any(a + 1e-7 < b for a, b in zip(scores, scores[1:])):
            raise AssertionError("Ranking not descending")
    elif name == "graph_summary":
        near(field(r, "nodes", "num_nodes", "node_count"), len(g))
        near(field(r, "edges", "num_edges", "edge_count"), g.number_of_edges())
        near(field(r, "density"), nx.density(g))
    elif name == "clustering_coefficient":
        near(field(r, "average_clustering"), nx.average_clustering(g, weight=None))
    elif name == "node_similarity":
        a, b = args["node_a"], args["node_b"]
        h = g.to_undirected()
        aa, bb = set(h[a]), set(h[b])
        near(
            field(r, "jaccard", "jaccard_similarity"), len(aa & bb) / len(aa | bb) if aa | bb else 0
        )
    elif name in ("shortest_path_unweighted", "shortest_path_weighted", "reachability"):
        a, b = args["source"], args["target"]
        reachable = nx.has_path(g, a, b)
        if not reachable:
            if field(r, "reachable") is not False:
                raise AssertionError("Expected unreachable")
        else:
            if name == "reachability" and r.get("reachable") is not True:
                raise AssertionError("Expected reachable")
            path = ids(field(r, "path"))
            if (
                path[0] != a
                or path[-1] != b
                or any(not g.has_edge(u, v) for u, v in zip(path, path[1:]))
            ):
                raise AssertionError("Invalid path")
            weight = "weight" if name == "shortest_path_weighted" else None
            cost = sum(g[u][v].get("weight", 1) if weight else 1 for u, v in zip(path, path[1:]))
            near(cost, nx.shortest_path_length(g, a, b, weight=weight))
    elif name == "articulation_points_bridges":
        if set(ids(field(r, "articulation_points"))) != set(nx.articulation_points(g)):
            raise AssertionError("Wrong articulation points")
        near(field(r, "bridge_count", "num_bridges"), len(list(nx.bridges(g))))
    elif name == "connected_components":
        near(field(r, "num_components", "count"), nx.number_connected_components(g.to_undirected()))
    elif name == "strongly_connected_components":
        near(field(r, "num_components", "count"), nx.number_strongly_connected_components(g))
    elif name == "maximal_cliques":
        near(
            field(r, "max_size", "maximum_clique_size", "largest_clique_size"),
            max(map(len, nx.find_cliques(g))),
        )
    elif name == "minimum_spanning_tree":
        near(field(r, "total_weight", "weight"), nx.minimum_spanning_tree(g).size(weight="weight"))
        h = store.get(output["result_graph_id"])._graph
        if set(h) != set(g) or not nx.is_tree(h):
            raise AssertionError("MST subgraph invalid")
    elif name == "max_flow_min_cut":
        h = g.copy()
        for u, v, d in h.edges(data=True):
            d["capacity"] = d.get("weight", 1)
        near(
            field(r, "max_flow", "max_flow_value", "flow_value"),
            nx.maximum_flow_value(h, args["source"], args["sink"]),
        )
    elif name == "bipartite_matching":
        near(
            field(r, "matching_size", "size", "num_matches"),
            len(nx.bipartite.maximum_matching(g)) / 2,
        )
    elif name == "bipartite_check":
        if field(r, "is_bipartite", "bipartite") != nx.is_bipartite(g):
            raise AssertionError("Wrong bipartiteness")
    elif name == "topological_sort":
        order = ids(field(r, "order", "ordering", "topological_order"))
        pos = {v: i for i, v in enumerate(order)}
        if (
            set(order) != set(g)
            or len(order) != len(g)
            or any(pos[u] >= pos[v] for u, v in g.edges)
        ):
            raise AssertionError("Invalid topological order")
    elif name == "motif_count":
        near(
            field(r, "count", "triangles", "triangle_count", "total_triangles"),
            sum(nx.triangles(g).values()) // 3,
        )
    elif name == "k_core":
        h = store.get(output["result_graph_id"])._graph
        if set(h) != set(nx.k_core(g)):
            raise AssertionError("Wrong core subgraph")
        near(field(r, "max_core_number", "k"), max(nx.core_number(g).values()))
    elif name == "ego_network":
        h = store.get(output["result_graph_id"])._graph
        expected = nx.ego_graph(g, args["node"])
        if set(h) != set(expected) or set(h.edges) != set(expected.edges):
            raise AssertionError("Wrong ego subgraph")
    elif name == "k_hop_neighborhood":
        h = store.get(output["result_graph_id"])._graph
        expected = nx.ego_graph(g, args["node"], radius=args.get("k", 2))
        if set(h) != set(expected):
            raise AssertionError("Wrong k-hop subgraph")
    elif name == "diameter_eccentricity":
        near(field(r, "diameter"), nx.diameter(g))
        near(field(r, "radius"), nx.radius(g))
    elif name == "degree_distribution":
        near(
            field(r, "mean_degree", "average_degree", "avg_degree"),
            sum(dict(g.degree()).values()) / len(g),
        )
    elif name == "girvan_newman":
        expected = next(nx.community.girvan_newman(g))
        h = store.get(output["result_graph_id"])._graph
        largest = max(map(len, expected))
        if len(h) != largest or not any(set(h) == set(c) for c in expected):
            raise AssertionError("First split/largest community differs from NetworkX")
    elif name in ("louvain", "label_propagation"):
        groups = field(r, "communities") if isinstance(r, dict) else r
        sets = [set(store.get(c["graph_id"]).nodes()) for c in groups]
        if set.union(*sets) != set(g) or sum(map(len, sets)) != len(g):
            raise AssertionError("Communities do not partition nodes")
        if "modularity" in r:
            near(r["modularity"], nx.community.modularity(g, sets, weight=None))
    elif name == "greedy_coloring":
        groups = field(r, "color_classes", "groups")
        colors = {}
        for c in groups:
            for n in ids(field(c, "members", "nodes")):
                colors[n] = c["color"]
        if set(colors) != set(g) or any(colors[u] == colors[v] for u, v in g.edges):
            raise AssertionError("Invalid coloring")
    elif name == "link_prediction":
        expected = {(u, v): s for u, v, s in nx.adamic_adar_index(g)}
        for row in entries(r):
            u, v = ids([row["source"], row["target"]])
            near(row["score"], expected.get((u, v), expected.get((v, u))))
    elif name == "hits":
        hubs, auth = nx.hits(g, max_iter=1000, tol=1e-12)
        for row in field(r, "hubs"):
            near(field(row, "hub", "score"), hubs[row["id"]])
        for row in field(r, "authorities"):
            near(field(row, "authority", "score"), auth[row["id"]])
    elif name == "node_embedding_similarity":
        rows = entries(r)
        if not rows or len({v["id"] for v in rows}) != len(rows):
            raise AssertionError("Invalid embedding ranking")
        if any(
            v["id"] == args["node"] or v["id"] not in g or not -1.000001 <= v["score"] <= 1.000001
            for v in rows
        ):
            raise AssertionError("Invalid cosine or node")
    else:
        raise AssertionError("No oracle")


def kinds(name):
    if name in ("bipartite_matching", "bipartite_check"):
        return ["bipartite"]
    if name == "topological_sort":
        return ["dag"]
    if name == "hits":
        return ["hits"]
    if name == "strongly_connected_components":
        return ["directed", "dag"]
    if name in (
        "degree_centrality",
        "betweenness_centrality",
        "closeness_centrality",
        "pagerank",
        "personalized_pagerank",
        "graph_summary",
    ):
        return ["base", "disconnected", "directed"]
    if name == "k_core":
        return ["base", "karate", "directed"]
    if name in (
        "girvan_newman",
        "clustering_coefficient",
        "ego_network",
        "maximal_cliques",
        "articulation_points_bridges",
        "motif_count",
    ):
        return ["base", "karate"]
    return ["base"]


def test_candidate(path):
    m = json.loads(path.read_text())
    name = m["name"]
    run = load_module(path.with_name("tool.py")).run
    checks = []
    for kind in kinds(name):
        g = fixture(kind)
        # HITS oracle uses the same unweighted adjacency as the requested tool.
        if name == "hits":
            for _, _, d in g.edges(data=True):
                d.pop("weight", None)
        s = GraphStore()
        s.add("fixture", g)
        args = parameters(m, g)
        with deadline(10):
            output = run(s, **args)
        if output.get("status") != "ok":
            raise AssertionError(f"{kind}: {output}")
        if len(json.dumps(output, allow_nan=False).encode()) > 8192:
            raise AssertionError("Output exceeds contract byte limit")
        oracle(name, g, output["result"], s, output, args)
        s2 = GraphStore()
        s2.add("fixture", g)
        with deadline(10):
            again = run(s2, **args)
        if output != again:
            raise AssertionError("Not deterministic")
        checks.append(kind + ": oracle/invariants, output bound, determinism")
    with deadline(3):
        invalid = run(GraphStore(), graph_id="missing")
    if invalid.get("status") != "error":
        raise AssertionError("Unknown graph not rejected")
    checks.append("unknown graph rejected")
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT / "tools"))
    args = parser.parse_args()
    reports = []
    candidates = {}
    for path in sorted(Path(args.source).glob("*/*/tool.json")):
        m = json.loads(path.read_text())
        record = {
            "implementation_id": m["implementation_id"],
            "source": str(path.relative_to(ROOT)),
            "name": m["name"],
        }
        try:
            record["checks"] = test_candidate(path)
            record["passed"] = True
            candidates.setdefault(m["name"], []).append(path)
        except Exception as e:
            record.update(passed=False, reason=f"{type(e).__name__}: {e}")
        reports.append(record)

    # Prefer manifest options that allow node-specific comparisons and explicit weighting.
    def rank(path):
        m = json.loads(path.read_text())
        p = m["parameters"]["properties"]
        return (
            -sum(k in p for k in ["weighted", "node", "exclude_source", "community_index"]),
            str(path),
        )

    selected = {}
    target = ROOT / "registry/tools"
    for family, paths in sorted(candidates.items()):
        chosen = sorted(paths, key=rank)[0]
        m = json.loads(chosen.read_text())
        dest = target / family / chosen.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        for old in (target / family).iterdir():
            if old != dest and old.is_dir():
                shutil.rmtree(old)
        hashes = {}
        for filename in ("tool.py", "tool.json", "README.md"):
            source = chosen.with_name(filename)
            shutil.copyfile(source, dest / filename)
            hashes[filename] = hashlib.sha256(source.read_bytes()).hexdigest()
        selected[family] = {"implementation_id": m["implementation_id"], "sha256": hashes}
    report = {
        "networkx_version": nx.__version__,
        "note": "Synthetic oracle tests; not official public-set end-to-end accuracy. Unrecognised output schemas fail curation without implying an algorithm bug. Embeddings use invariant checks, community heuristics partition/modularity checks.",
        "tested": len(reports),
        "passed": sum(r["passed"] for r in reports),
        "selected": selected,
        "implementations": reports,
    }
    (ROOT / "evaluation").mkdir(exist_ok=True)
    (ROOT / "evaluation/curation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Tested {len(reports)} implementations; {report['passed']} passed; selected {len(selected)} families."
    )
    for name in sorted({r["name"] for r in reports} - set(selected)):
        print("NO SELECTION:", name)
        for r in reports:
            if r["name"] == name:
                print(" ", r["implementation_id"], r.get("reason"))


if __name__ == "__main__":
    main()
