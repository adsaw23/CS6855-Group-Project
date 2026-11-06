"""Resolve answer expressions against recorded tool results."""

import math


def pointer(value, path):
    if not path:
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    trail = ""
    for raw in path[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit() or int(part) >= len(value):
                raise ValueError(
                    f'{trail or "/"} is an array of {len(value)} items: use a numeric index, e.g. {trail}/0/id for a node ID, not {part!r}'
                )
            value = value[int(part)]
        elif isinstance(value, dict):
            if part not in value:
                raise ValueError(f'{trail or "/"} has fields {list(value)}, not {part!r}')
            value = value[part]
        else:
            raise ValueError(f'{trail or "/"} is a scalar; no further path is valid')
        trail += "/" + raw
    return value


def evidence_examples(results, limit=32):
    """Bounded pointer hints derived only from actual successful tool results."""
    examples = []

    def walk(value, ref):
        if len(examples) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, ref + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, ref + "/" + str(i))
        elif isinstance(value, (str, int, float, bool)) and len(str(value)) <= 100:
            examples.append({"ref": ref, "value": value})

    for call, result in reversed(list(results.items())):
        if result.get("status") == "ok":
            walk(result.get("result"), call + "#/result")
    return examples


def evaluate(expr, results, used=None, depth=0):
    if depth > 20:
        raise ValueError("Expression nesting too deep")
    if used is None:
        used = set()

    def ev(x):
        return evaluate(x, results, used, depth + 1)

    if not isinstance(expr, dict):
        return expr
    if "ref" in expr:
        call, sep, path = expr["ref"].partition("#")
        if not sep or call not in results or results[call].get("status") != "ok":
            raise ValueError(
                "Evidence must reference a successful tool call as call_id#/result/..."
            )
        used.add(call)
        return pointer(results[call], path)
    op = expr.get("op")
    args = [ev(a) for a in expr.get("args", [])]
    if op == "get":
        return pointer(args[0], expr["path"])
    if op == "pluck":
        return [pointer(v, expr["path"]) for v in args[0]]
    if op == "length":
        return len(args[0])
    if op == "sum":
        return sum(args[0])
    if op == "max":
        return max(args[0])
    if op == "min":
        return min(args[0])
    if op == "subtract":
        return args[0] - args[1]
    if op == "equal":
        return args[0] == args[1]
    if op == "greater":
        return args[0] > args[1]
    if op == "slice":
        return args[0][expr.get("start", 0) : expr.get("stop")]
    if op == "exclude":
        return [v for v in args[0] if pointer(v, expr.get("path", "")) != args[1]]
    if op == "sort":
        return sorted(
            args[0], key=lambda v: pointer(v, expr["path"]), reverse=expr.get("descending", True)
        )
    if op == "argmax":
        return max(args[0], key=lambda v: pointer(v, expr["path"]))
    raise ValueError(f"Unsupported evidence operation: {op}")


def supported_value(expression, answer_type, results):
    used = set()
    value = evaluate(expression, results, used)
    if not used:
        raise ValueError("An answered question needs tool evidence, not a literal answer")
    if answer_type == "node" and isinstance(value, dict):
        value = value.get("id")
    elif answer_type in ("node_list", "path") and isinstance(value, list):
        value = [item.get("id") if isinstance(item, dict) else item for item in value]
    valid = {
        "number": type(value) in (int, float) and math.isfinite(value),
        "boolean": type(value) is bool,
        "node": isinstance(value, str),
        "text": isinstance(value, str),
        "node_list": isinstance(value, list) and all(isinstance(x, str) for x in value),
        "path": isinstance(value, list) and all(isinstance(x, str) for x in value),
    }
    if not valid.get(answer_type, False):
        raise ValueError(f"Value does not match answer type {answer_type}")
    return value, sorted(used)
