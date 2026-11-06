"""Load tool manifests, validate arguments, and run tools with a timeout."""

import copy
import hashlib
import importlib.util
import json
import signal
from contextlib import contextmanager
from pathlib import Path
import jsonschema
from graphkit.contract import error


@contextmanager
def deadline(seconds):
    # Unix runner: preempts even a non-terminating student implementation.
    if not hasattr(signal, "setitimer"):
        yield
        return

    def expired(signum, frame):
        raise TimeoutError("Tool exceeded execution time limit")

    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def load_module(path):
    name = "tool_" + hashlib.sha256(str(path).encode()).hexdigest()[:20]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Registry:
    def __init__(self, root="registry/tools"):
        self.entries = {}
        for path in sorted(Path(root).glob("*/*/tool.json")):
            manifest = json.loads(path.read_text())
            name = manifest["name"]
            if name in self.entries:
                raise ValueError(f"More than one curated implementation of {name}")
            jsonschema.Draft7Validator.check_schema(manifest["parameters"])
            self.entries[name] = (manifest, load_module(path.with_name("tool.py")).run)
        if not self.entries:
            raise ValueError("No curated tools. Run python scripts/curate_tools.py first.")

    def prepare_arguments(self, name, arguments):
        arguments = dict(arguments)
        manifest = self.entries[name][0]
        if manifest.get("category") == "centrality":
            for parameter in ("weighted", "use_weights"):
                if parameter in manifest["parameters"]["properties"]:
                    arguments.setdefault(parameter, False)
        return arguments

    def schemas(self):
        schemas = []
        for name, (manifest, _) in self.entries.items():
            parameters = copy.deepcopy(manifest["parameters"])
            parameters["additionalProperties"] = False
            description = manifest["description"]
            if manifest.get("category") == "centrality":
                flags = [p for p in ("weighted", "use_weights") if p in parameters["properties"]]
                for parameter in flags:
                    parameters["properties"][parameter]["default"] = False
                if flags:
                    description = (
                        "COURSE RUNNER DEFAULT: omitted weighting flags are false (unweighted). "
                        "Pass true only when the question explicitly requests weights. "
                        "Original implementation description: " + description
                    )
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas

    def execute(self, name, store, arguments):
        if name not in self.entries:
            return error(f"Unknown tool {name}")
        manifest, run = self.entries[name]
        try:
            arguments = self.prepare_arguments(name, arguments)
            jsonschema.validate(
                arguments, {**manifest["parameters"], "additionalProperties": False}
            )
            with deadline(30):
                result = run(store, **arguments)
            if not isinstance(result, dict) or result.get("status") not in ("ok", "error"):
                return error("Tool returned an invalid contract")
            encoded = json.dumps(result, allow_nan=False).encode()
            if len(encoded) > 8192:
                return error("Tool exceeded 8192-byte output limit")
            if result.get("result_graph_id"):
                store.get(result["result_graph_id"])
            return result
        except Exception as exc:
            return error(f"{type(exc).__name__}: {exc}")
