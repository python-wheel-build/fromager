#!/usr/bin/env python3
"""Extract benchmark dependencies from pyproject.toml.

Outputs [project.optional-dependencies.benchmark] as requirements.txt format
to stdout. Used by benchmark-backfill.yml to maintain a single source of truth.

Usage:
    python extract_deps.py pyproject.toml | uv pip install -r - --system
"""

import sys
import tomllib
from pathlib import Path


def main() -> int:
    """Extract and print benchmark dependencies from pyproject.toml."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pyproject.toml>", file=sys.stderr)
        return 1

    pyproject_path = Path(sys.argv[1])

    if not pyproject_path.exists():
        print(f"Error: File not found: {pyproject_path}", file=sys.stderr)
        return 1

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"Error: Invalid TOML: {e}", file=sys.stderr)
        return 1

    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    benchmark_deps = optional_deps.get("benchmark")

    if benchmark_deps is None:
        print(
            "Error: No [project.optional-dependencies.benchmark] found",
            file=sys.stderr,
        )
        return 1

    if not benchmark_deps:
        print("Warning: Benchmark dependencies list is empty", file=sys.stderr)
        return 0

    for dep in benchmark_deps:
        print(dep)

    return 0


if __name__ == "__main__":
    sys.exit(main())
