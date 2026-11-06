#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator.queries import read_queries

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("spreadsheet")
    p.add_argument("--out", default="queries_public.json")
    a = p.parse_args()
    Path(a.out).write_text(json.dumps(read_queries(a.spreadsheet), indent=2) + "\n")
