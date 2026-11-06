#!/usr/bin/env python3
"""Run: python run_queries.py --queries queries.json --out answers.json"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from graphkit.graph import GraphStore
from orchestrator.agent import Agent
from orchestrator.llm import LLMClient
from orchestrator.queries import read_queries
from orchestrator.registry import Registry

ROOT = Path(__file__).resolve().parent


def trace_names(queries):
    """Map each query ID to a unique, path-safe trace file stem."""
    names, used = {}, set()
    for q in queries:
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", q["query_id"]) or "query"
        candidate, n = stem, 2
        while candidate in used:
            candidate, n = f"{stem}_{n}", n + 1
        used.add(candidate)
        names[q["query_id"]] = candidate
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", default="answers.json")
    parser.add_argument("--data", default=str(ROOT / "data"))
    parser.add_argument("--registry", default=str(ROOT / "registry/tools"))
    parser.add_argument("--cache", default=str(ROOT / ".cache/llm"))
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--only", nargs="+", help="Query IDs to run")
    args = parser.parse_args()
    if args.max_calls < 1:
        parser.error("--max-calls must be positive")
    all_queries = read_queries(args.queries)
    queries = all_queries
    if args.only:
        unknown = set(args.only) - {q["query_id"] for q in all_queries}
        if unknown:
            parser.error(f"Unknown query IDs: {sorted(unknown)}")
        queries = [q for q in all_queries if q["query_id"] in args.only]
    registry = Registry(args.registry)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    trace_dir = out.parent / "traces"
    trace_dir.mkdir(exist_ok=True)
    records = {}
    if args.only and out.exists():
        records = {a["query_id"]: a for a in json.loads(out.read_text(encoding="utf-8"))}
    answers = list(records.values())
    stems = trace_names(all_queries)
    for query in queries:
        trace_path = trace_dir / (stems[query["query_id"]] + ".jsonl")
        with trace_path.open("w", encoding="utf-8") as f:

            def trace(event):
                f.write(
                    json.dumps(
                        {"timestamp": datetime.now(timezone.utc).isoformat(), **event},
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                )
                f.flush()

            trace({"event": "query", "query": query})
            agent = None
            preflight_tools = []
            try:
                # Reset derived graphs per question, making runs order-independent.
                store = GraphStore.from_directory(args.data)
                if not query["question"]:
                    raise ValueError("The query file gives no question text for this ID.")
                # Record missing-data evidence as an actual tool result.
                # With no graph field, the planner decides from the question text.
                if query["graph_id"] is not None and query["graph_id"] not in {
                    g["graph_id"] for g in store.list_graphs()
                }:
                    from orchestrator.utilities import list_graphs

                    preflight_tools.append("builtin.list_graphs")
                    trace(
                        {
                            "event": "tool_call",
                            "call_id": "preflight",
                            "name": "list_graphs",
                            "arguments": {},
                            "output": list_graphs(store),
                        }
                    )
                    raise ValueError(
                        f"Graph {query['graph_id']!r} is not loaded. Add the official dataset to {args.data}."
                    )
                client = LLMClient(args.cache, trace)
                agent = Agent(registry, store, client, trace, args.max_calls)
                result = agent.run(query)
            except Exception as exc:
                message = str(exc)
                # No request headers or credentials are logged.
                key = os.environ.get("GEMINI_API_KEY")
                if key:
                    message = message.replace(key, "[REDACTED]")
                trace({"event": "error", "error": message})
                result = {
                    "status": "error",
                    "answer_text": message,
                    "answer": {"type": "text", "value": message},
                    "tools_used": agent.tools_used if agent else preflight_tools,
                }
            result = {
                "query_id": query["query_id"],
                **result,
                "trace_file": os.path.relpath(trace_path, out.parent),
            }
            trace({"event": "final_answer", "answer": result})
            records[query["query_id"]] = result
            answers = [records[q["query_id"]] for q in all_queries if q["query_id"] in records]
        temporary = out.with_suffix(out.suffix + ".tmp")
        temporary.write_text(
            json.dumps(answers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(out)
        print(f"{query['query_id']}: {result['status']}")
    if not queries:
        out.write_text("[]\n", encoding="utf-8")
    return 1 if any(a["status"] == "error" for a in answers) else 0


if __name__ == "__main__":
    raise SystemExit(main())
