# Datasets

The CSV files and `graphs.json` come from
[smiitm/mas-project](https://github.com/smiitm/mas-project/tree/8127602f50c87ca92798beb53c834dbe02744676/data),
commit `8127602f50c87ca92798beb53c834dbe02744676`.

[SOURCE_README.md](SOURCE_README.md) is the unchanged upstream documentation,
including source and license details. File URLs and hashes are recorded in
`evaluation/dataset_provenance.json`.

| Graph | Nodes | Edges | Directed | Weights |
| --- | ---: | ---: | --- | --- |
| airports | 500 | 20,058 | Yes | Distance in km |
| karate | 34 | 78 | No | None |
| lesmis | 77 | 254 | No | Shared chapters |
| courses | 21 | 29 | Yes | None |
| projects | 26 | 28 | No | None |

Each graph has `nodes.csv` and `edges.csv`. `graphs.json` defines its direction,
weight setting and attribute types. For an unweighted graph, the loader uses
unit weights even if the CSV has a weight column.

To download the same files again, run `python scripts/fetch_datasets.py` from
the project root. It refuses to overwrite files whose contents differ.

The loader also accepts separate JSON graph files containing `graph_id`,
`directed`, `nodes` and `edges` (or `links`). Nodes can be IDs or objects with an
`id` field. Edges can be `[source, target, weight]` lists or objects with `source`,
`target` and an optional `weight`. Do not define the same graph in both formats.
