# Graph Analytics Orchestrator

CS6855 course project, Group 8. The runner uses Gemini to choose tools from the class
registry, run them, and answer questions about the bundled graphs.

## Team

| Member | Roll number |
| --- | --- |
| Aditya Anand Sawant | CS23B003 |
| Derek Oliver F | ED23B016 |
| Shailendra Kumar | EE25D014 |
| E Dharanishwar | EE26E022 |
| Novikov Mikhail | GE26Z858 |

## Setup

Use Python 3.11 or later on Linux or WSL. Run these commands from this directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
read -rsp 'Google AI Studio API key: ' GEMINI_API_KEY
export GEMINI_API_KEY
```

The API key is read from `GEMINI_API_KEY`. `.env.example` lists the settings;
`.env` files are not loaded automatically. Use a Google project with free-tier
access, as required by the assignment.

The default model is `gemini-3.5-flash-lite`. Set `GEMINI_MODEL` to use another
Gemini model that supports function calling. Requests are spaced 4.2 seconds
apart to stay within the quota observed during testing. If your quota differs,
set `GEMINI_MIN_INTERVAL`. Temporary provider errors are retried up to four
attempts; a persistent failure is recorded as an error.

## Run the public questions

```bash
python run_queries.py --queries queries_public.json --out answers_public.json
```

The workbook can also be passed directly to `--queries`. Only the query ID,
question and graph name reach the planner; expected answers are ignored.
JSON, JSONL and CSV inputs are also supported.

Answers are saved after each question. Each answer links to its JSONL file in
`traces/`, which records the model requests, tool arguments, results and final
answer. To retry individual questions without replacing the other answers:

```bash
python run_queries.py --queries queries_public.json --out answers_public.json --only q05 q23
```

Successful model responses are cached in `.cache/llm`. Cache hits are marked in
the traces. Delete that directory if you want a fresh model run.

## Project layout

- `orchestrator/`: planner loop, Gemini client, input reader and answer expressions.
- `graphkit/`: graph store and the interface used by the registry tools.
- `registry/tools/`: 33 selected implementations, copied unchanged from `tools/`.
- `registry/builtins/`: manifests for lookup, filtering and graph projections.
- `data/`: the five graph datasets. See [data/README.md](data/README.md) for sources.
- `scripts/` and `tests/`: tool selection, scoring, trace replay and local tests.
- `evaluation/`: scores, dataset hashes and earlier test runs.

The supplied root README and tool files are unchanged. This file covers the
orchestrator setup.

## How it works

The runner reads tool manifests at startup. Gemini chooses a tool and its
arguments; the executor validates them and calls the selected implementation.
A tool that creates a subgraph returns `result_graph_id`, which can be passed
to the next tool. Each question starts with a fresh graph store.

Final answers are computed from references to recorded tool results. The
expression evaluator supports operations such as selecting a ranking, counting
items and subtracting scores. It rejects literal answers with no evidence.
Ambiguous questions request clarification; unavailable capabilities return
`unsupported`.

Centrality tools default to unweighted calculations unless weighting is
explicitly requested. Tools have a 30-second timeout and an 8 KB output limit.
The planner aims for five calls and has a hard limit of eight, configurable
with `--max-calls`.

## Check the results

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py --expected 'CS6855_Public_Query_Set (1).xlsx' --answers answers_public.json --data data
python scripts/audit_traces.py
```

The recorded public run passes **30/30 questions**. All **27 local tests** pass,
including 54 comparisons against NetworkX on random graphs. The trace audit
replays all 30 cases and checks their answer expressions. The final run used
68 tool calls: 2.27 per question on average, with a maximum of seven.

These checks cover the public set, not the hidden questions. A trace proves
where a value came from; interpreting the question correctly still matters.
The report describes the failures found during development and the fixes.

To repeat tool selection from the supplied submissions:

```bash
python scripts/curate_tools.py --source tools
```

This tests 186 implementations and rebuilds the selected registry. The selection
results and source hashes are in `evaluation/curation.json`.

## Report and submission

The group and member details are filled in. `report.md` contains a proposed
responsibility allocation; confirm the actual contributions before submission.
The team has confirmed free-tier use of Codex and Google AI Studio. To rebuild the PDF and ZIP:

```bash
pip install -r requirements-dev.txt
python scripts/build_report.py
python scripts/package_submission.py
```

The PDF is limited to four pages. The archive is `dist/submission_draft.zip`;
its name reflects the contribution confirmation still needed. It includes code, selected
tools, datasets, answers, traces and the report. API keys, model caches and
virtual environments are excluded. The report contains the required AI-assistance
acknowledgment.
