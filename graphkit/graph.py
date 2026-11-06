"""Graph storage and CSV/JSON loading for the registry tools."""

import csv
import hashlib
import json
import math
from pathlib import Path
import networkx as nx


class Graph:
    def __init__(self, graph_id, graph, description=""):
        self.graph_id = graph_id
        self._graph = graph.copy()
        self.description = description
        self.parent_id = None
        self.directed = graph.is_directed()
        self.weighted = graph.graph.get(
            "weighted", any("weight" in d for _, _, d in graph.edges(data=True))
        )

    def nodes(self):
        return list(self._graph.nodes)

    def edges(self):
        return [(u, v, d.get("weight", 1.0)) for u, v, d in self._graph.edges(data=True)]

    def number_of_nodes(self):
        return self._graph.number_of_nodes()

    def number_of_edges(self):
        return self._graph.number_of_edges()

    def has_node(self, node):
        return node in self._graph

    def has_edge(self, u, v):
        return self._graph.has_edge(u, v)

    def node_attrs(self, node):
        return dict(self._graph.nodes[node])

    def edge_attrs(self, u, v):
        return dict(self._graph[u][v])

    def label(self, node):
        return str(self._graph.nodes[node].get("label", node))

    def weight(self, u, v):
        return self._graph[u][v].get("weight", 1.0)

    def out_neighbors(self, node):
        return {v: d.get("weight", 1.0) for v, d in self._graph[node].items()}

    def in_neighbors(self, node):
        if not self.directed:
            return self.out_neighbors(node)
        return {v: d.get("weight", 1.0) for v, d in self._graph.pred[node].items()}

    def undirected_neighbors(self, node):
        result = self.in_neighbors(node)
        for v, w in self.out_neighbors(node).items():
            result[v] = min(w, result.get(v, w))
        return result

    def neighbors(self, node):
        return self.undirected_neighbors(node)


class GraphStore:
    def __init__(self):
        self._graphs = {}

    def add(self, graph_id, graph, description=""):
        if graph_id in self._graphs:
            raise ValueError(f"Duplicate graph id: {graph_id}")
        self._graphs[graph_id] = Graph(graph_id, graph, description)
        return graph_id

    def get(self, graph_id):
        return self._graphs[graph_id]

    def list_graphs(self):
        return [
            {
                "graph_id": k,
                "description": g.description,
                "parent_id": g.parent_id,
                "nodes": g.number_of_nodes(),
                "edges": g.number_of_edges(),
                "directed": g.directed,
                "weighted": g.weighted,
            }
            for k, g in self._graphs.items()
        ]

    def _register(self, parent, graph, description):
        payload = [
            parent,
            description,
            sorted(graph.nodes),
            sorted((u, v, sorted(d.items())) for u, v, d in graph.edges(data=True)),
        ]
        graph_id = (
            parent.split("__")[0]
            + "__"
            + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        )
        if graph_id not in self._graphs:
            self.add(graph_id, graph, description)
            self._graphs[graph_id].parent_id = parent
        return graph_id

    def subgraph(self, graph_id, nodes, description=""):
        g = self.get(graph_id)._graph
        nodes = list(nodes)
        if any(n not in g for n in nodes):
            raise ValueError("Unknown subgraph node")
        chosen = set(nodes)
        # NetworkX's small subgraph view may iterate a set in hash-dependent order.
        # Preserve parent order so graph IDs and tie-breaking survive new processes.
        edges = ((u, v, d) for u, v, d in g.edges(data=True) if u in chosen and v in chosen)
        child = self._copy_subgraph(g, chosen, edges)
        return self._register(graph_id, child, description)

    def edge_subgraph(self, graph_id, edges, description=""):
        g = self.get(graph_id)._graph
        edges = list(edges)
        if any(not g.has_edge(u, v) for u, v in edges):
            raise ValueError("Unknown subgraph edge")
        chosen = set(edges)
        if not g.is_directed():
            chosen |= {(v, u) for u, v in edges}
        nodes = {n for edge in edges for n in edge}
        edges = ((u, v, d) for u, v, d in g.edges(data=True) if (u, v) in chosen)
        child = self._copy_subgraph(g, nodes, edges)
        return self._register(graph_id, child, description)

    @staticmethod
    def _copy_subgraph(graph, nodes, edges):
        child = graph.__class__()
        child.graph.update(graph.graph)
        child.add_nodes_from((n, dict(d)) for n, d in graph.nodes(data=True) if n in nodes)
        child.add_edges_from((u, v, dict(d)) for u, v, d in edges)
        return child

    def _load_csv_graph(self, directory, graph_id, meta):
        if (
            not isinstance(graph_id, str)
            or Path(graph_id).name != graph_id
            or graph_id in (".", "..")
        ):
            raise ValueError("Invalid graph ID in dataset manifest")
        if type(meta.get("directed")) is not bool or type(meta.get("weighted")) is not bool:
            raise ValueError(f"{graph_id}: directed and weighted must be booleans")
        g = nx.DiGraph() if meta["directed"] else nx.Graph()
        g.graph["weighted"] = meta["weighted"]
        casts = {"str": str, "int": int, "float": float}

        def attributes(row, declared, reserved):
            values = {k: v for k, v in row.items() if k not in reserved}
            for name, kind in declared.items():
                if kind not in casts or name not in values:
                    raise ValueError(f"{graph_id}: invalid or missing attribute {name}")
                values[name] = casts[kind](values[name])
                if kind == "float" and not math.isfinite(values[name]):
                    raise ValueError(f"{graph_id}: non-finite attribute {name}")
            return values

        with (directory / graph_id / "nodes.csv").open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                node = row["id"]
                if not node or node in g:
                    raise ValueError(f"{graph_id}: empty or duplicate node {node!r}")
                g.add_node(node, **attributes(row, meta.get("node_attributes", {}), {"id"}))
        with (directory / graph_id / "edges.csv").open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                u, v = row["source"], row["target"]
                if u not in g or v not in g:
                    raise ValueError(f"{graph_id}: unknown edge endpoint")
                if g.has_edge(u, v):
                    raise ValueError(f"{graph_id}: duplicate edge {u}, {v}")
                attrs = attributes(
                    row, meta.get("edge_attributes", {}), {"source", "target", "weight"}
                )
                if meta["weighted"]:
                    weight = float(row["weight"])
                    if not math.isfinite(weight):
                        raise ValueError(f"{graph_id}: non-finite edge weight")
                    attrs["weight"] = weight
                g.add_edge(u, v, **attrs)
        self.add(graph_id, g, meta.get("description", ""))

    @classmethod
    def from_directory(cls, directory):
        store = cls()
        directory = Path(directory)
        manifest = directory / "graphs.json"
        if manifest.is_file():
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("graphs.json must map graph IDs to metadata")
            for graph_id, meta in metadata.items():
                store._load_csv_graph(directory, graph_id, meta)
        for path in sorted(directory.glob("*.json")):
            if path == manifest:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, dict)
                or "nodes" not in raw
                or not ("edges" in raw or "links" in raw)
            ):
                raise ValueError(f"{path}: expected nodes and edges arrays")
            g = nx.DiGraph() if raw.get("directed", False) else nx.Graph()
            for node in raw["nodes"]:
                attrs = dict(node) if isinstance(node, dict) else {"id": node}
                node_id = str(attrs.pop("id"))
                if node_id in g:
                    raise ValueError(f"{path}: duplicate node {node_id}")
                g.add_node(node_id, **attrs)
            for edge in raw.get("edges", raw.get("links", [])):
                attrs = (
                    dict(edge)
                    if isinstance(edge, dict)
                    else dict(zip(["source", "target", "weight"], edge))
                )
                u, v = str(attrs.pop("source")), str(attrs.pop("target"))
                if u not in g or v not in g:
                    raise ValueError(f"{path}: edge references unknown node")
                if g.has_edge(u, v):
                    raise ValueError(f"{path}: duplicate edge {u}, {v}")
                if "weight" in attrs and (
                    isinstance(attrs["weight"], bool)
                    or not isinstance(attrs["weight"], (int, float))
                    or not math.isfinite(attrs["weight"])
                ):
                    raise ValueError(f"{path}: invalid weight")
                g.add_edge(u, v, **attrs)
            store.add(raw.get("graph_id", path.stem), g, raw.get("description", ""))
        return store
