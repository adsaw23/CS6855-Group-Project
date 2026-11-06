# Graph Analytics Orchestrator

CS6855 | Group: 8

## Design

The project uses a plain Python loop with Gemini function calling. At startup,
the runner reads the selected tool manifests and sends their descriptions and
argument schemas to the model. The model chooses a tool, the executor runs it,
and the result is returned for the next step. Questions contain only an ID,
text and graph name. Expected answers from the workbook are kept out of this loop.

The executor checks arguments against the manifest, applies a 30-second timeout,
and rejects invalid JSON or results larger than 8 KB. It aims to finish within
five tool calls, with a hard limit of eight to allow lookups and error recovery.
Each question gets a fresh graph store.

For multi-step questions, tools return a result_graph_id for the extracted
community, core or neighborhood. Later tools use this ID. Extra utilities handle
graph metadata, name lookup, attribute filters and graph projections. Their
schemas are also loaded from manifests.

The graph store implements the interface used by the class tools, with NetworkX
providing storage. It loads the CSV files using the direction, weights and
attribute types in graphs.json. Subgraphs preserve parent node and edge order
so their IDs stay stable between processes.

## Building an answer

Each tool response includes an evidence_ref. To finish a question, the model
provides an expression that selects or combines values from those responses.
The executor evaluates the expression and checks the answer type. It can select
ranked nodes, count results or calculate a difference, but it cannot accept a
literal answer with no supporting tool call.

Ambiguous questions ask for clarification. Questions about missing attributes
or unavailable algorithms return unsupported. Missing graph files and provider
failures return error. The trace records every model request, tool call and final
answer, including cache hits. These checks establish where an answer came from;
they cannot guarantee that the model chose the right interpretation.

<!-- PAGE -->

## Tool selection and datasets

The selection script tested all 186 supplied implementations and chose one for
each of 33 tool families. It compares numerical results with NetworkX and checks
output size, repeatability, invalid inputs and returned subgraphs. Community and
embedding heuristics are checked using partition, modularity and similarity
properties. A schema mismatch can rule out a tool even when its algorithm is
correct. Selected source files and manifests are unchanged.

The five datasets were copied from the data directory of smiitm/mas-project at
commit 8127602f50c87ca92798beb53c834dbe02744676. Only datasets and their documentation
were copied. Source URLs and SHA-256 hashes are in evaluation/dataset_provenance.json;
data/SOURCE_README.md preserves the upstream source and license information.

The graphs are airports (500 nodes, 20,058 edges), karate (34, 78), lesmis (77, 254),
courses (21, 29), and projects (26, 28). Airports is directed and weighted by
distance. Lesmis uses shared chapters as weights. The other graphs are unweighted;
courses is directed.

## Results

The final public run passes 30 of 30 questions against the supplied workbook.
The scorer uses 0.1% numeric tolerance, compares rankings in order and checks
that course orderings respect every prerequisite. Answers are in
answers_public.json; the score is in evaluation/public_score.json.

The run used 68 graph and utility calls, averaging 2.27 per question. Twenty-nine
questions used at most five calls. q11 used seven because it made extra metadata,
lookup and projection calls. Reducing those calls is still a useful optimization.

All 30 traces pass a separate audit that reruns the tools, compares their complete
outputs and evaluates the recorded answer expressions. The local suite has 27
passing tests, including 54 numerical comparisons on six seeded random graphs.
It also checks input parsing, source hashes, ambiguity, provider errors, subgraph
chaining and incremental reruns. The tests pass from an extracted submission ZIP.

Before the datasets were available, smaller fixture runs helped test the planner
and executor. Earlier failed runs are retained under evaluation/ to document the
changes. The final score was reached after fixes and retries; it was not the
first-run score. Public-set success does not guarantee hidden-set accuracy, and
future runs can still fail when the provider is unavailable or a quota is reached.

<!-- PAGE -->

## Failures and fixes

### Provider errors

The original Flash model repeatedly returned HTTP 503, and a 2.5 Flash probe
returned 404. Flash-Lite probes succeeded, so the default was changed to
3.5 Flash-Lite. Later runs still encountered temporary 503 errors. Requests are
now spaced 4.2 seconds apart, and retries honor the provider's delay hints. Cases
that exhausted their retries were rerun. Failed requests never supply graph facts.

### Invalid evidence references

Early q08 and q09 attempts chose the right algorithm but invented call IDs in
the final expression. The transport ID was not reliably copied by the model.
Tool responses now include an explicit evidence_ref. If finalization fails,
the executor shows valid references and example paths from the actual results.
It also converts returned node objects to IDs when the answer type requires one.

q30 exposed a related problem: the model tried to answer a planarity question
from memory although no planarity tool was loaded. The executor rejected the
literal answer. Recovery guidance now asks the model to check tool availability
and return unsupported when the required capability is missing.

### Wrong scope or metric

For q22, the first plan counted 44 triangles containing the center instead of
all 96 triangles in its ego network. The prompt now requires extracting the
neighborhood before computing statistics inside it. For q26, the model chose a
closeness measure without asking. A question-level check now requests the metric
when proximity or importance is unspecified.

q05 used the PageRank implementation's weighted default, which treated route
distance as importance and changed the ranking. The executor now defaults
centrality calculations to unweighted unless the question requests weights.
It logs the effective arguments and leaves the supplied tool files unchanged.

### Unstable subgraph IDs

Replaying the traces revealed that small NetworkX subgraphs could iterate nodes
in a different order between processes. This changed their generated IDs.
The graph store now copies nodes and edges in parent order. A regression test
runs with three Python hash seeds, and the affected public cases were rerun.

<!-- PAGE -->

## Team responsibilities


Aditya Anand Sawant (CS23B003) — Executor. Own the execution
loop in orchestrator/agent.py, argument validation and timeouts in
orchestrator/registry.py, graph storage in graphkit/, and answer validation in
orchestrator/evidence.py. Lead subgraph chaining, error recovery and integration
across the planner, tools and runner.

Derek Oliver F (ED23B016) — Planner lead. Own the planning prompt and tool-choice
logic in orchestrator/agent.py, ambiguity checks in orchestrator/clarification.py,
and model calls, caching and retries in orchestrator/llm.py. Check that multi-step
plans use returned graph IDs and handle unsupported questions correctly.

Shailendra Kumar (EE25D014) — Tool curator. Own scripts/curate_tools.py and
scripts/fetch_datasets.py. Review numerical reference checks, implementation
selection, registry manifests and dataset provenance. Check the 33 selected tool
families while preserving the supplied tool files unchanged.

E Dharanishwar (EE26E022) — Evaluation lead. Own tests/test_system.py,
scripts/evaluate.py and scripts/audit_traces.py. Review public-set scoring,
regression coverage, recorded tool outputs and failure analysis. Check that
answers_public.json agrees with the traces and workbook.

Novikov Mikhail (GE26Z858) — Integration and demo lead. Own run_queries.py,
orchestrator/queries.py, PROJECT_README.md, scripts/build_report.py and
scripts/package_submission.py. Check input handling, the one-command run,
clean installation, report layout and ZIP contents; prepare the demonstration.
Coordinate technical integration with Aditya.

## AI assistance

OpenAI Codex was used for debugging and testing. Google AI Studio's Gemini provides runtime function calling.
Both services were used on free tiers, as confirmed by the team.

## Running the project

PROJECT_README.md contains setup instructions. The API key is supplied through
GEMINI_API_KEY. Run python run_queries.py --queries queries_public.json --out
answers_public.json to evaluate the public set. The report and ZIP can be rebuilt
with scripts/build_report.py and scripts/package_submission.py after confirming
the contribution statement.

## References

Course Project Graph Analytics Orchestrator.pdf; CS6855_Public_Query_Set (1).xlsx;
and the supplied class tool registry.

Dataset repository: https://github.com/smiitm/mas-project. The pinned commit and
individual file hashes are recorded in evaluation/dataset_provenance.json.
The upstream dataset README attributes the airports data to OpenFlights under
ODbL, karate to Zachary, and lesmis to Knuth's Stanford GraphBase.

NetworkX is used for graph storage and reference calculations in the tests.
Google API documentation: https://aistudio.google.com/docs/openai.
