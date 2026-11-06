# Graph Analytics Orchestrator

CS6855 | Group: 8

## Design

The project uses a straightforward Python loop with Gemini function calling. At startup, the runner reads the selected tool manifests and sends the tool descriptions along with their argument schemas to the model. The model selects a tool, the executor runs it, and the result is returned for the next step. Questions contain only an ID, text, and graph name. The expected answers from the workbook are kept outside this loop.

The executor validates the arguments against the manifest, applies a 30-second timeout, and rejects invalid JSON or results larger than 8 KB. It is designed to complete the task within five tool calls, with a hard limit of eight calls to handle lookups and error recovery. Each question is provided with a fresh graph store.

For multi-step questions, the tools return a result_graph_id for the extracted community, core, or neighborhood, which is then used by subsequent tools. Additional utilities are available for handling graph metadata, name lookup, attribute filters, and graph projections. Their schemas are also loaded from the manifests.

The graph store implements the interface required by the class tools, with NetworkX used for graph storage. It loads the CSV files based on the direction, weights, and attribute types specified in graphs.json. Subgraphs preserve the parent node and edge order so that their IDs remain stable across different processes.

## Building an answer

Each tool response includes an evidence_ref. To complete a question, the model provides an expression that selects or combines values from those responses. The executor evaluates the expression and checks the answer type. It can select ranked nodes, count results, or calculate a difference, but it cannot accept a literal answer without a supporting tool call.

Ambiguous questions require clarification. Questions involving missing attributes or unavailable algorithms return unsupported. Missing graph files and provider failures return error. The trace records every model request, tool call, and final answer, including cache hits. These checks establish where an answer came from; however, they cannot guarantee that the model selected the correct interpretation.
<!-- PAGE -->

## Tool selection and datasets

The selection script tested all 186 supplied implementations and selected one for each of the 33 tool families. It compares numerical results with NetworkX and checks output size, repeatability, handling of invalid inputs, and returned subgraphs. Community and embedding heuristics are evaluated using partition, modularity, and similarity properties. A schema mismatch can rule out a tool even when the underlying algorithm is correct. The selected source files and manifests remain unchanged.

The five datasets were copied from the data directory of smiitm/mas-project at commit 8127602f50c87ca92798beb53c834dbe02744676. Only the datasets and their documentation were copied. Source URLs and SHA-256 hashes are provided in evaluation/dataset_provenance.json, while data/SOURCE_README.md preserves the upstream source and license information.

The graphs are airports (500 nodes, 20,058 edges), karate (34, 78), lesmis (77, 254), courses (21, 29), and projects (26, 28). Airports is directed and weighted by distance. Lesmis uses shared chapters as weights. The remaining graphs are unweighted, while courses is directed.

## Results

The final public run successfully passes all 30 out of 30 questions against the supplied workbook. The scorer uses a 0.1% numeric tolerance, compares rankings in the required order, and checks that course orderings satisfy every prerequisite. The answers are available in answers_public.json, while the score is recorded in evaluation/public_score.json.

The run used a total of 55 graph and utility calls, with an average of 1.83 calls per question. Every question was completed using five or fewer calls; the most was four, for q15, which filtered the German airports before ranking them.

All 30 traces pass a separate audit that reruns the tools, compares their complete outputs, and evaluates the recorded answer expressions. The local test suite contains 29 passing tests, including 54 numerical comparisons across six seeded random graphs. It also checks input parsing, source hashes, ambiguity handling, provider errors, subgraph chaining, and incremental reruns. The tests also pass when executed from an extracted submission ZIP.

Before the datasets were available, smaller fixture runs were used to test the planner and executor. Earlier failed runs are retained under evaluation/ to document the changes made during development. The final score was achieved after fixes and retries; it was not the score obtained in the first run. Public-set success does not guarantee accuracy on the hidden set, and future runs may still fail if the provider is unavailable or a quota limit is reached.

<!-- PAGE -->

## Failures and fixes

### Provider errors

The original Flash model repeatedly returned HTTP 503 errors, while a 2.5 Flash probe returned 404. Flash-Lite probes were successful, so the default model was changed to 3.5 Flash-Lite. However, later runs still encountered temporary 503 errors. Requests are now spaced 4.2 seconds apart, and retries follow the delay hints provided by the provider. Cases that exhausted their retries were rerun. Failed requests are never used to supply graph facts.

### Invalid evidence references

During the initial attempts for q08 and q09, the model selected the correct algorithm but generated incorrect call IDs in the final expression. The transport ID was not consistently copied by the model. To address this issue, tool responses now include an explicit `evidence_ref`. If finalization fails, the executor provides valid references and example paths from the actual results. It also converts returned node objects into IDs when the answer type requires them.

q30 exposed a related issue: the model attempted to answer a planarity question using its existing knowledge, even though no planarity tool was loaded. The executor rejected the literal answer. Recovery guidance now asks the model to verify tool availability and return `unsupported` when the required capability is not available.

### Wrong scope or metric

For q22, the initial plan counted 44 triangles containing the center instead of considering all 96 triangles in its ego network. The prompt now requires extracting the neighbourhood before computing statistics within it. For q26, the model selected a closeness measure without asking for clarification. A question-level check now requests the metric whenever proximity or importance is not clearly specified.

q05 used the weighted default of the PageRank implementation, which treated route distance as importance and changed the ranking. The executor now uses unweighted centrality calculations by default, unless the question explicitly requests weights. It also logs the effective arguments while keeping the supplied tool files unchanged.

### Unstable subgraph IDs

During trace replay, it was observed that small NetworkX subgraphs could iterate over nodes in a different order across processes. This resulted in changes to their generated IDs. To address this issue, the graph store now copies nodes and edges in the same order as their parent graph. A regression test runs with three different Python hash seeds, and the affected public cases were rerun.

<!-- PAGE -->

## Team responsibilities


### Aditya Anand Sawant (CS23B003) — Executor

Responsible for the execution loop in `orchestrator/agent.py`, argument validation and timeouts in `orchestrator/registry.py`, graph storage in `graphkit/`, and answer validation in `orchestrator/evidence.py`. Lead the implementation of subgraph chaining, error recovery, and integration across the planner, tools, and runner.

### Derek Oliver F (ED23B016) — Planner Lead

Responsible for the planning prompt and tool-selection logic in `orchestrator/agent.py`, ambiguity checks in `orchestrator/clarification.py`, and model calls, caching, and retries in `orchestrator/llm.py`. Ensure that multi-step plans use the returned graph IDs and that unsupported questions are handled correctly.

### Novikov Mikhail (GE26Z858) — Tool Curator

Responsible for `scripts/curate_tools.py` and `scripts/fetch_datasets.py`. Review numerical reference checks, implementation selection, registry manifests, and dataset provenance. Verify all 33 selected tool families while ensuring that the supplied tool files remain unchanged.

### E Dharanishwar (EE26E022) — Evaluation Lead

Responsible for `tests/test_system.py`, `scripts/evaluate.py`, and `scripts/audit_traces.py`. Review public-set scoring, regression test coverage, recorded tool outputs, and failure analysis. Ensure that `answers_public.json` matches the traces and the supplied workbook.

### Shailendra Kumar (EE25D014) — Integration and Demo Lead

Responsible for `run_queries.py`, `orchestrator/queries.py`, `PROJECT_README.md`, `scripts/build_report.py`, and `scripts/package_submission.py`. Verify input handling, the one-command execution, clean installation, report layout, and ZIP contents. Also, prepare the project demonstration and coordinate technical integration with Aditya.

## AI assistance

OpenAI Codex was used for debugging and testing purposes. Google AI Studio's Gemini was used for runtime function calling. Both services were used under their respective free-tier plans, as confirmed by the team.

## References

Course Project Graph Analytics Orchestrator.pdf; CS6855_Public_Query_Set (1).xlsx;
and the supplied class tool registry.

Dataset repository: https://github.com/smiitm/mas-project. The pinned commit and
individual file hashes are recorded in evaluation/dataset_provenance.json.
The upstream dataset README attributes the airports data to OpenFlights under
ODbL, karate to Zachary, and lesmis to Knuth's Stanford GraphBase.

NetworkX is used for graph storage and reference calculations in the tests.
Google API documentation: https://aistudio.google.com/docs/openai.
