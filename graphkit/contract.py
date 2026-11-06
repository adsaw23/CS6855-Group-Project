MAX_OUTPUT_BYTES = 8192
DEFAULT_TOP_K = 10
MAX_TOP_K = 100


def ok(result, summary, result_graph_id=None):
    out = {"status": "ok", "result": result, "summary": summary}
    if result_graph_id is not None:
        out["result_graph_id"] = result_graph_id
    return out


def error(message):
    return {"status": "error", "error": str(message)}


def get_graph(store, graph_id):
    try:
        return store.get(graph_id), None
    except (KeyError, TypeError):
        return None, error(f"Unknown graph {graph_id!r}. Use list_graphs.")


def check_node(g, node, name="node", param=None):
    name = param or name
    if not isinstance(node, str) or not g.has_node(node):
        return error(f"Unknown {name}: {node!r}. Use lookup_node.")
    return None


def check_top_k(top_k=DEFAULT_TOP_K):
    if type(top_k) is not int or not 1 <= top_k <= MAX_TOP_K:
        return None, error(f"top_k must be an integer from 1 to {MAX_TOP_K}")
    return top_k, None


def node_ref(g, node, **attrs):
    return {"id": node, "label": g.label(node), **attrs}
