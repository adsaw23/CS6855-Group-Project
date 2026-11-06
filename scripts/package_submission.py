#!/usr/bin/env python3
"""Build a credential-free submission ZIP with only the selected tool registry."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md",
    "REGISTRY_ORIGINAL_README.md",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    "run_queries.py",
    "queries_public.json",
    "answers_public.json",
    "report.md",
    "report.pdf",
    "CS6855_Public_Query_Set (1).xlsx",
]
DIRECTORIES = [
    "graphkit",
    "orchestrator",
    "registry",
    "data",
    "scripts",
    "tests",
    "evaluation",
    "traces",
]


def main():
    target = ROOT / "dist/CS6855_Group_project_8.zip"
    target.parent.mkdir(exist_ok=True)
    paths = [ROOT / f for f in FILES]
    for directory in DIRECTORIES:
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in [".pyc", ".tmp"]
            and not p.name.startswith(".")
        )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(paths)):
            if not path.is_file():
                raise FileNotFoundError(path)
            z.write(path, Path("graph_analytics_orchestrator") / path.relative_to(ROOT))
    print(target)


if __name__ == "__main__":
    main()
