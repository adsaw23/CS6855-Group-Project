#!/usr/bin/env python3
"""Download the datasets from a pinned repository commit."""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/smiitm/mas-project"
COMMIT = "8127602f50c87ca92798beb53c834dbe02744676"
FILES = ["data/graphs.json", "data/README.md"] + [
    f"data/{graph}/{name}.csv"
    for graph in ["airports", "karate", "lesmis", "courses", "projects"]
    for name in ["nodes", "edges"]
]


def main():
    def fetch(path):
        url = f"https://raw.githubusercontent.com/smiitm/mas-project/{COMMIT}/{path}"
        response = requests.get(url, timeout=(15, 60))
        response.raise_for_status()
        return path, response.content, url

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(fetch, FILES))
    records = []
    for source, content, url in files:
        relative = "data/SOURCE_README.md" if source == "data/README.md" else source
        destination = ROOT / relative
        if destination.exists() and destination.read_bytes() != content:
            raise ValueError(f"Refusing to overwrite different existing file: {relative}")
        records.append(
            {
                "source_path": source,
                "local_path": relative,
                "url": url,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    for (_, content, _), record in zip(files, records):
        destination = ROOT / record["local_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    report = {
        "repository": REPOSITORY,
        "commit": COMMIT,
        "scope": "Dataset files only. No orchestrator, tool implementations or other group code copied.",
        "files": records,
    }
    (ROOT / "evaluation/dataset_provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Downloaded and hashed {len(records)} dataset/documentation files at commit {COMMIT}.")


if __name__ == "__main__":
    main()
