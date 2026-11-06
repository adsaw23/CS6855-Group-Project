import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import networkx as nx
from graphkit.graph import GraphStore
from orchestrator.registry import Registry
from orchestrator.agent import Agent
from orchestrator.evidence import supported_value
from orchestrator.queries import read_queries
from orchestrator.utilities import lookup_node, filter_nodes, project_graph, inspect_graph
from scripts.curate_tools import oracle, parameters

ROOT = Path(__file__).resolve().parents[1]


def tool_call(name, args, call_id):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


class ScriptedClient:
    """Protocol fixture only; never used by the production runner."""

    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, messages, tools):
        response = next(self.responses)
        return response(messages) if callable(response) else response


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = Registry(ROOT / "registry/tools")

    def store(self):
        s = GraphStore()
        g = nx.Graph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])
        s.add("test", g)
        return s

    def test_curated_sources_unchanged(self):
        report = json.loads((ROOT / "evaluation/curation.json").read_text())
        self.assertEqual(33, len(report["selected"]))
        for name, entry in report["selected"].items():
            impl = entry["implementation_id"].split(".")[-1]
            for file, digest in entry["sha256"].items():
                for root in ["tools", "registry/tools"]:
                    path = ROOT / root / name / impl / file
                    if root == "tools" and not path.exists():
                        continue
                    self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_spreadsheet_no_answer_leakage(self):
        queries = read_queries(ROOT / "CS6855_Public_Query_Set (1).xlsx")
        self.assertEqual(30, len(queries))
        self.assertEqual({"query_id", "question", "graph_id"}, set(queries[0]))
        self.assertIsNone(queries[23]["graph_id"])

    def test_query_path_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_text(json.dumps([{"query_id": "../escape", "question": "x"}]))
            with self.assertRaises(ValueError):
                read_queries(p)
            p.write_text(json.dumps([{"query_id": "x", "question": "x"}] * 2))
            with self.assertRaises(ValueError):
                read_queries(p)

    def test_evidence_literal_and_failed_call_rejected(self):
        with self.assertRaises(ValueError):
            supported_value(42, "number", {})
        with self.assertRaises(ValueError):
            supported_value(
                {"ref": "bad#/result"}, "number", {"bad": {"status": "error", "result": 42}}
            )
        with self.assertRaises(ValueError):
            supported_value({"ref": "x#/result"}, "number", {"x": {"status": "ok", "result": True}})

    def test_node_reference_normalization_and_pointer_recovery(self):
        from orchestrator.evidence import evidence_examples

        results = {
            "x": {
                "status": "ok",
                "result": [
                    {"id": "a", "label": "Alice", "score": 0.8},
                    {"id": "b", "label": "Bob", "score": 0.2},
                ],
            }
        }
        value, _ = supported_value({"ref": "x#/result/1"}, "node", results)
        self.assertEqual("b", value)
        value, _ = supported_value({"ref": "x#/result"}, "node_list", results)
        self.assertEqual(["a", "b"], value)
        with self.assertRaisesRegex(ValueError, "is an array"):
            supported_value({"ref": "x#/result/top_nodes"}, "node", results)
        self.assertIn({"ref": "x#/result/1/score", "value": 0.2}, evidence_examples(results))
        self.assertLessEqual(len(evidence_examples(results, limit=2)), 2)

    def test_evidence_arithmetic_and_rankings(self):
        r = {
            "x": {"status": "ok", "result": [{"id": "a", "score": 0.6}, {"id": "b", "score": 0.4}]}
        }
        value, _ = supported_value(
            {
                "op": "subtract",
                "args": [{"ref": "x#/result/0/score"}, {"ref": "x#/result/1/score"}],
            },
            "number",
            r,
        )
        self.assertAlmostEqual(0.2, value)
        value, _ = supported_value(
            {
                "op": "pluck",
                "args": [{"op": "exclude", "args": [{"ref": "x#/result"}, "a"], "path": "/id"}],
                "path": "/id",
            },
            "node_list",
            r,
        )
        self.assertEqual(["b"], value)

    def test_single_tool_agent(self):
        logs = []
        client = ScriptedClient(
            [
                tool_call("graph_summary", {"graph_id": "test"}, "one"),
                tool_call(
                    "finish",
                    {
                        "status": "answered",
                        "answer_type": "number",
                        "expression": json.dumps({"ref": "one#/result/edges"}),
                    },
                    "final",
                ),
            ]
        )
        result = Agent(self.registry, self.store(), client, logs.append).run(
            {"graph_id": "test", "question": "How many edges?"}
        )
        self.assertEqual({"type": "number", "value": 4}, result["answer"])
        self.assertTrue(any(e["event"] == "answer_evidence" for e in logs))
        self.assertEqual("one#/result", logs[0]["output"]["evidence_ref"])

    def test_subgraph_agent_chain(self):
        def second(messages):
            output = json.loads(messages[-1]["content"])
            return tool_call("graph_summary", {"graph_id": output["result_graph_id"]}, "two")

        client = ScriptedClient(
            [
                tool_call("ego_network", {"graph_id": "test", "node": "d"}, "one"),
                second,
                tool_call(
                    "finish",
                    {
                        "status": "answered",
                        "answer_type": "number",
                        "expression": json.dumps({"ref": "two#/result/nodes"}),
                    },
                    "final",
                ),
            ]
        )
        logs = []
        answer = Agent(self.registry, self.store(), client, logs.append).run(
            {"question": "Size of d ego", "graph_id": "test"}
        )
        self.assertEqual(2, answer["answer"]["value"])
        calls = [e for e in logs if e["event"] == "tool_call"]
        self.assertEqual(calls[0]["output"]["result_graph_id"], calls[1]["arguments"]["graph_id"])

    def test_literal_finish_recovers(self):
        logs = []
        client = ScriptedClient(
            [
                tool_call(
                    "finish",
                    {"status": "answered", "answer_type": "number", "expression": "4"},
                    "bad",
                ),
                tool_call("graph_summary", {"graph_id": "test"}, "one"),
                tool_call(
                    "finish",
                    {
                        "status": "answered",
                        "answer_type": "number",
                        "expression": '{"ref":"one#/result/edges"}',
                    },
                    "final",
                ),
            ]
        )
        answer = Agent(self.registry, self.store(), client, logs.append).run(
            {"question": "edges", "graph_id": "test"}
        )
        self.assertEqual("answered", answer["status"])
        self.assertEqual("error", logs[0]["output"]["status"])

    def test_nonanswer_statuses(self):
        for status in ["clarification_needed", "unsupported", "error"]:
            with self.subTest(status=status):
                client = ScriptedClient(
                    [tool_call("finish", {"status": status, "reason": "Explanation"}, "final")]
                )
                self.assertEqual(
                    status,
                    Agent(self.registry, self.store(), client, lambda x: None).run(
                        {"question": "x"}
                    )["status"],
                )

    def test_call_budget(self):
        logs = []
        client = ScriptedClient(
            [
                tool_call("graph_summary", {"graph_id": "test"}, "one"),
                tool_call("graph_summary", {"graph_id": "test"}, "two"),
                tool_call("finish", {"status": "error", "reason": "Budget exhausted"}, "final"),
            ]
        )
        a = Agent(self.registry, self.store(), client, logs.append, max_calls=1).run(
            {"question": "x"}
        )
        self.assertEqual(1, len(a["tools_used"]))
        self.assertEqual("error", logs[1]["output"]["status"])

    def test_parameter_validation(self):
        for args in [
            {"graph_id": "test", "top_k": 0},
            {"graph_id": "test", "top_k": True},
            {"graph_id": "test", "bogus": 1},
        ]:
            self.assertEqual(
                "error", self.registry.execute("degree_centrality", self.store(), args)["status"]
            )

    def test_unknown_node_and_graph(self):
        self.assertEqual(
            "error",
            self.registry.execute(
                "ego_network", self.store(), {"graph_id": "test", "node": "missing"}
            )["status"],
        )
        self.assertEqual(
            "error",
            self.registry.execute("graph_summary", self.store(), {"graph_id": "missing"})["status"],
        )

    def test_ambiguous_lookup_and_filter(self):
        s = GraphStore()
        g = nx.DiGraph()
        g.add_nodes_from(
            [
                ("CDG", {"label": "Paris CDG", "country": "France"}),
                ("ORY", {"label": "Paris Orly", "country": "France"}),
                ("LHR", {"label": "London Heathrow", "country": "UK"}),
            ]
        )
        g.add_weighted_edges_from([("CDG", "ORY", 3), ("ORY", "CDG", 5)])
        s.add("air", g)
        self.assertEqual(2, lookup_node(s, "air", ["Paris"])["result"]["Paris"]["count"])
        sub = filter_nodes(s, "air", "country", "france", True)["result_graph_id"]
        self.assertEqual({"CDG", "ORY"}, set(s.get(sub).nodes()))
        self.assertFalse(s.get(sub).directed)
        self.assertEqual(3, s.get(sub).weight("CDG", "ORY"))
        with self.assertRaises(ValueError):
            filter_nodes(s, "air", "missing", "x")
        self.assertNotIn("fare", inspect_graph(s, "air")["result"]["edge_attributes"])

    def test_projection_does_not_modify_parent(self):
        s = self.store()
        s.get("test")._graph["a"]["b"]["weight"] = 9
        sub = project_graph(s, "test", "unit_weights")["result_graph_id"]
        self.assertEqual(1, s.get(sub).weight("a", "b"))
        self.assertEqual(9, s.get("test").weight("a", "b"))

    def test_data_loader_preserves_ids_attributes_and_isolates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sample.json"
            p.write_text(
                json.dumps(
                    {
                        "directed": True,
                        "nodes": [{"id": "001", "label": "One"}, "002", "iso"],
                        "edges": [{"source": "001", "target": "002", "weight": 2}],
                    }
                )
            )
            g = GraphStore.from_directory(d).get("sample")
            self.assertEqual("One", g.label("001"))
            self.assertTrue(g.has_node("iso"))
            self.assertEqual({}, g.out_neighbors("002"))
            self.assertEqual({"001": 2}, g.in_neighbors("002"))
            p.write_text(json.dumps({"nodes": ["a"], "edges": [["a", "missing"]]}))
            with self.assertRaises(ValueError):
                GraphStore.from_directory(d)

    def test_cli_missing_data_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_text(
                json.dumps([{"query_id": "q1", "graph_id": "absent", "question": "Edges?"}])
            )
            out = Path(d) / "answers.json"
            data = Path(d) / "data"
            data.mkdir()
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run_queries.py"),
                    "--queries",
                    str(p),
                    "--out",
                    str(out),
                    "--data",
                    str(data),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, process.returncode)
            answer = json.loads(out.read_text())[0]
            self.assertEqual("error", answer["status"])
            self.assertTrue((Path(d) / answer["trace_file"]).is_file())
            self.assertIn("is not loaded", answer["answer_text"])
            self.assertEqual(["builtin.list_graphs"], answer["tools_used"])

    def test_llm_cache_and_trace_without_secret(self):
        from orchestrator.llm import LLMClient

        response = {
            "choices": [
                {
                    "message": tool_call(
                        "finish", {"status": "unsupported", "reason": "No tool"}, "final"
                    )
                }
            ]
        }
        with tempfile.TemporaryDirectory() as d, patch.dict(
            "os.environ", {"GEMINI_API_KEY": "test-secret", "GEMINI_MIN_INTERVAL": "0"}
        ), patch("orchestrator.llm.requests.post") as post:
            post.return_value.ok = True
            post.return_value.status_code = 200
            post.return_value.json.return_value = response
            logs = []
            client = LLMClient(d, logs.append)
            messages = [{"role": "user", "content": "hello"}]
            first = client.complete(messages, [])
            second = client.complete(messages, [])
            self.assertEqual(first, second)
            self.assertEqual(1, post.call_count)
            self.assertNotIn("test-secret", json.dumps(logs))
            self.assertTrue(logs[-1]["cached"])

    def test_provider_error_is_diagnostic_and_redacts_key(self):
        from orchestrator.llm import LLMClient

        with tempfile.TemporaryDirectory() as d, patch.dict(
            "os.environ", {"GEMINI_API_KEY": "test-secret", "GEMINI_MIN_INTERVAL": "0"}
        ), patch("orchestrator.llm.requests.post") as post, patch("orchestrator.llm.time.sleep"):
            post.return_value.ok = False
            post.return_value.status_code = 503
            post.return_value.headers = {}
            post.return_value.json.return_value = [
                {"error": {"message": "Unavailable for test-secret"}}
            ]
            logs = []
            client = LLMClient(d, logs.append)
            with self.assertRaisesRegex(RuntimeError, r"Unavailable for \[REDACTED\]"):
                client.complete([{"role": "user", "content": "hello"}], [])
            self.assertEqual(4, post.call_count)
            self.assertNotIn("test-secret", json.dumps(logs))
            self.assertEqual("Unavailable for [REDACTED]", logs[-1]["provider_error"])
            self.assertEqual([], list(Path(d).glob("*.json")))

    def test_retry_hint_preserves_request_context(self):
        from orchestrator.llm import LLMClient
        from unittest.mock import Mock

        limited = Mock(ok=False, status_code=429, headers={})
        limited.json.return_value = [{"error": {"message": "Please retry in 23.778s."}}]
        success = Mock(ok=True, status_code=200)
        success.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        with tempfile.TemporaryDirectory() as d, patch.dict(
            "os.environ", {"GEMINI_API_KEY": "test-secret", "GEMINI_MIN_INTERVAL": "0"}
        ), patch("orchestrator.llm.requests.post", side_effect=[limited, success]) as post, patch(
            "orchestrator.llm.time.sleep"
        ) as sleep:
            messages = [{"role": "user", "content": "Original question"}]
            result = LLMClient(d).complete(messages, [])
            self.assertEqual("ok", result["content"])
            sleep.assert_called_once_with(24.778)
            self.assertEqual(messages, post.call_args.kwargs["json"]["messages"])

    def test_generic_ambiguity_guard(self):
        from orchestrator.clarification import clarification_reason

        self.assertIsNotNone(clarification_reason("How close are Alice and Bob?"))
        self.assertIsNotNone(clarification_reason("Which member is most important?"))
        self.assertIsNone(clarification_reason("How close are Alice and Bob in hops?"))
        self.assertIsNone(clarification_reason("Which member is most important by PageRank?"))
        self.assertIsNone(clarification_reason("Which five nodes are most relevant to Alice?"))
        logs = []
        agent = Agent(self.registry, self.store(), ScriptedClient([]), logs.append)
        result = agent.run({"graph_id": "test", "question": "How close are Alice and Bob?"})
        self.assertEqual("clarification_needed", result["status"])
        self.assertEqual("clarification_check", logs[0]["event"])

    def test_course_csv_loader_attributes_and_unweighted_semantics(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sample").mkdir()
            meta = {
                "sample": {
                    "directed": True,
                    "weighted": False,
                    "description": "CSV fixture",
                    "node_attributes": {"level": "int"},
                    "edge_attributes": {"count": "int"},
                }
            }
            (root / "graphs.json").write_text(json.dumps(meta))
            (root / "sample/nodes.csv").write_text(
                "id,label,level\n001,First,1\n002,Second,2\niso,Isolate,3\n"
            )
            edges = root / "sample/edges.csv"
            edges.write_text("source,target,weight,count\n001,002,99,4\n")
            store = GraphStore.from_directory(root)
            g = store.get("sample")
            self.assertFalse(g.weighted)
            self.assertTrue(g.directed)
            self.assertEqual(1, g.weight("001", "002"))
            self.assertEqual(4, g.edge_attrs("001", "002")["count"])
            self.assertEqual(2, g.node_attrs("002")["level"])
            self.assertTrue(g.has_node("iso"))
            child = store.subgraph("sample", ["001", "002"])
            self.assertFalse(store.get(child).weighted)
            edges.write_text("source,target,weight,count\n001,002,1,4\n001,002,1,4\n")
            with self.assertRaisesRegex(ValueError, "duplicate edge"):
                GraphStore.from_directory(root)

    def test_downloaded_dataset_integrity(self):
        provenance = json.loads((ROOT / "evaluation/dataset_provenance.json").read_text())
        self.assertEqual(12, len(provenance["files"]))
        for file in provenance["files"]:
            self.assertEqual(
                file["sha256"], hashlib.sha256((ROOT / file["local_path"]).read_bytes()).hexdigest()
            )
        store = GraphStore.from_directory(ROOT / "data")
        expected = {
            "airports": (500, 20058),
            "karate": (34, 78),
            "lesmis": (77, 254),
            "courses": (21, 29),
            "projects": (26, 28),
        }
        self.assertEqual(set(expected), {g["graph_id"] for g in store.list_graphs()})
        for name, (n, m) in expected.items():
            graph = store.get(name)
            self.assertEqual((n, m), (graph.number_of_nodes(), graph.number_of_edges()))
        self.assertFalse(store.get("karate").weighted)
        self.assertIsInstance(store.get("airports").node_attrs("MAA")["lat"], float)

    def test_centrality_defaults_and_explicit_weight_override(self):
        store = self.store()
        g = store.get("test")._graph
        g["a"]["b"]["weight"] = 20
        store.get("test").weighted = True
        for args, weight in [
            ({"graph_id": "test", "top_k": 100}, None),
            ({"graph_id": "test", "top_k": 100, "weighted": True}, "weight"),
        ]:
            output = self.registry.execute("pagerank", store, args)
            expected = nx.pagerank(g, weight=weight, tol=1e-12)
            self.assertEqual("ok", output["status"])
            for row in output["result"]:
                self.assertAlmostEqual(expected[row["id"]], row["score"], places=5)
        self.assertTrue(
            self.registry.entries["pagerank"][0]["parameters"]["properties"]["weighted"]["default"]
        )
        advertised = next(s for s in self.registry.schemas() if s["function"]["name"] == "pagerank")
        self.assertFalse(advertised["function"]["parameters"]["properties"]["weighted"]["default"])

    def test_only_rerun_preserves_other_answers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            data = root / "data"
            data.mkdir()
            queries = root / "queries.json"
            out = root / "answers.json"
            queries.write_text(
                json.dumps(
                    [
                        {"query_id": q, "graph_id": "absent", "question": "Edges?"}
                        for q in ["q1", "q2"]
                    ]
                )
            )
            original = {
                "query_id": "q1",
                "status": "answered",
                "answer": {"type": "number", "value": 7},
                "tools_used": [],
            }
            out.write_text(json.dumps([original]))
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run_queries.py"),
                    "--queries",
                    str(queries),
                    "--out",
                    str(out),
                    "--data",
                    str(data),
                    "--only",
                    "q2",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, process.returncode)
            answers = json.loads(out.read_text())
            self.assertEqual(original, answers[0])
            self.assertEqual("q2", answers[1]["query_id"])

    def test_subgraphs_stable_across_hash_seeds(self):
        import os

        code = """import json
from graphkit.graph import GraphStore
s=GraphStore.from_directory('data')
a=s.subgraph('karate',['m1','m2','m3','m4','m14'],'clique')
b=s.edge_subgraph('karate',[('m1','m2'),('m1','m3')],'edges')
print(json.dumps([a,b,s.get(a).nodes(),s.get(b).edges()]))
"""
        outputs = []
        for seed in ["1", "2", "42"]:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                check=True,
            )
            outputs.append(result.stdout)
        self.assertEqual(1, len(set(outputs)))

    def test_random_graph_oracles(self):
        families = [
            "degree_centrality",
            "betweenness_centrality",
            "closeness_centrality",
            "pagerank",
            "graph_summary",
            "clustering_coefficient",
            "k_core",
            "maximal_cliques",
            "minimum_spanning_tree",
        ]
        for seed in range(6):
            g = nx.relabel_nodes(nx.gnp_random_graph(9, 0.4, seed=seed), lambda n: str(n))
            # Connect components for MST while retaining varied topology.
            parts = list(nx.connected_components(g))
            for a, b in zip(parts, parts[1:]):
                g.add_edge(min(a), min(b))
            for i, (u, v) in enumerate(sorted(g.edges)):
                g[u][v]["weight"] = (i % 7) + 1
            for name in families:
                with self.subTest(seed=seed, tool=name):
                    s = GraphStore()
                    s.add("fixture", g)
                    m = self.registry.entries[name][0]
                    args = parameters(m, g)
                    out = self.registry.execute(name, s, args)
                    self.assertEqual("ok", out["status"], out)
                    oracle(name, g, out["result"], s, out, args)


if __name__ == "__main__":
    unittest.main()
