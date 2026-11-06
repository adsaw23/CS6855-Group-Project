"""Graph lookup, filtering, and projection tools."""

import json
from pathlib import Path

from graphkit.contract import node_ref, ok


def list_graphs(store):
    return ok(store.list_graphs(), "Available graphs in this run.")


def inspect_graph(store, graph_id):
    g = store.get(graph_id)
    attributes = {}
    for n in g.nodes():
        for k, v in g.node_attrs(n).items():
            if k != "label":
                attributes.setdefault(k, set()).add(str(v))
    return ok(
        {
            "graph_id": graph_id,
            "description": g.description,
            "directed": g.directed,
            "weighted": g.weighted,
            "node_count": g.number_of_nodes(),
            "edge_count": g.number_of_edges(),
            "node_attributes": {
                k: {"values": sorted(v)[:30], "truncated": len(v) > 30}
                for k, v in attributes.items()
            },
            "edge_attributes": sorted({k for _, _, d in g._graph.edges(data=True) for k in d}),
        },
        "Graph metadata and available attributes; absent attributes cannot be assumed.",
    )


def lookup_node(store, graph_id, names):
    g = store.get(graph_id)
    result = {}
    for name in names:
        needle = name.casefold().strip()
        exact = [n for n in g.nodes() if n.casefold() == needle or g.label(n).casefold() == needle]
        found = exact or [
            n
            for n in g.nodes()
            if any(needle in str(v).casefold() for v in [n, *g.node_attrs(n).values()])
        ]
        result[name] = {"matches": [node_ref(g, n) for n in found[:20]], "count": len(found)}
    return ok(
        result, "Resolve each name only when it has one match; multiple matches need clarification."
    )


def filter_nodes(store, graph_id, attribute, value, undirected=False):
    g = store.get(graph_id)
    if not any(attribute in g.node_attrs(n) for n in g.nodes()):
        raise ValueError(f"Unknown node attribute {attribute!r}; use inspect_graph")
    nodes = [
        n
        for n in g.nodes()
        if str(g.node_attrs(n).get(attribute, "")).casefold() == str(value).casefold()
    ]
    child = store.subgraph(graph_id, nodes, f"{attribute}={value}")
    if undirected:
        child = _undirected(store, child)
    return ok(
        {
            "node_count": len(nodes),
            "attribute": attribute,
            "value": value,
            "undirected": undirected,
        },
        f"Induced subgraph where {attribute}={value}.",
        child,
    )


def _undirected(store, graph_id):
    import networkx as nx

    g = store.get(graph_id)
    h = nx.Graph()
    h.add_nodes_from(g._graph.nodes(data=True))
    for u, v, d in g._graph.edges(data=True):
        if not h.has_edge(u, v) or d.get("weight", 1) < h[u][v].get("weight", 1):
            h.add_edge(u, v, **d)
    return store._register(graph_id, h, "Undirected projection; minimum reciprocal edge weight")


def project_graph(store, graph_id, mode):
    g = store.get(graph_id)
    if mode == "undirected":
        child = _undirected(store, graph_id)
    else:
        h = g._graph.copy()
        for _, _, d in h.edges(data=True):
            d["weight"] = 1.0
        child = store._register(graph_id, h, "Unit edge weights/capacities")
    return ok({"mode": mode}, f"Created {mode} graph.", child)


def schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


# Load the utility schemas alongside the registry tools.

BUILTIN_ROOT = Path(__file__).resolve().parents[1] / "registry/builtins"
SCHEMAS = []
FUNCTIONS = {}
for manifest_path in sorted(BUILTIN_ROOT.glob("*/tool.json")):
    manifest = json.loads(manifest_path.read_text())
    name = manifest["name"]
    FUNCTIONS[name] = globals()[name]
    SCHEMAS.append(
        {
            "type": "function",
            "function": {k: manifest[k] for k in ("name", "description", "parameters")},
        }
    )
