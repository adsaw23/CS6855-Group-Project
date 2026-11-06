#!/usr/bin/env python3
"""Replay recorded tool calls and verify answer expressions without an LLM/key."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graphkit.graph import GraphStore
from graphkit.contract import error
from orchestrator.registry import Registry
from orchestrator import utilities
from orchestrator.evidence import supported_value


def audit(answers_path, data_path):
    answers_path = Path(answers_path)
    registry = Registry(ROOT / "registry/tools")
    checks = []
    for answer in json.loads(answers_path.read_text()):
        store = GraphStore.from_directory(data_path)
        trace_path = answers_path.parent / answer["trace_file"]
        events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        assert (
            events[-1]["event"] == "final_answer" and events[-1]["answer"] == answer
        ), "Final trace/answer mismatch"
        results = {}
        calls = 0
        for event in events:
            if (
                event["event"] != "tool_call"
                or event["name"] == "finish"
                or not event.get("implementation_id")
            ):
                continue
            name, args = event["name"], event["arguments"]
            if name in utilities.FUNCTIONS:
                try:
                    output = utilities.FUNCTIONS[name](store, **args)
                    if len(json.dumps(output, allow_nan=False).encode()) > 8192:
                        output = error("Tool output exceeds 8192 bytes; narrow the request.")
                except Exception as exc:
                    output = error(f"{type(exc).__name__}: {exc}")
            else:
                assert event["implementation_id"] == registry.entries[name][0]["implementation_id"]
                output = registry.execute(name, store, args)
            output = {**output, "evidence_ref": event["call_id"] + "#/result"}
            output = json.loads(json.dumps(output, allow_nan=False))
            assert output == event["output"], f"{answer['query_id']}: replay mismatch in {name}"
            results[event["call_id"]] = output
            calls += 1
        if answer["status"] == "answered":
            evidence = [e for e in events if e["event"] == "answer_evidence"][-1]
            value, _ = supported_value(evidence["expression"], answer["answer"]["type"], results)
            assert value == answer["answer"]["value"], "Answer does not follow recorded evidence"
            for detail in evidence["details"]:
                supported_value(json.loads(detail["expression"]), detail["answer_type"], results)
        checks.append(
            {
                "query_id": answer["query_id"],
                "tool_calls_replayed": calls,
                "llm_calls": sum(e["event"] == "llm_request" for e in events),
                "cache_hits": sum(
                    e["event"] == "llm_response" and e.get("cached", False) for e in events
                ),
                "status": answer["status"],
                "passed": True,
            }
        )
    return {
        "scope": "Exact tool-output replay, final-answer consistency, and evidence-expression checks; semantic correctness is scored separately.",
        "data_manifest_sha256": hashlib.sha256(
            (Path(data_path) / "graphs.json").read_bytes()
        ).hexdigest(),
        "passed": len(checks),
        "total": len(checks),
        "results": checks,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--answers", default=str(ROOT / "answers_public.json"))
    p.add_argument("--data", default=str(ROOT / "data"))
    p.add_argument("--out", default=str(ROOT / "evaluation/trace_audit.json"))
    args = p.parse_args()
    result = audit(args.answers, args.data)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(f"Audited {result['passed']}/{result['total']} traces successfully.")
