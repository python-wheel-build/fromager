"""
Component benchmarks for Fromager.

These benchmarks test CPU-bound, pure Python operations using direct API calls.
They use CodSpeed's CPU simulation mode for deterministic, hardware-independent
measurements.

Focus: Core parsing and constraint checking that happens frequently during
dependency resolution.
"""

from packaging.version import Version

from fromager.constraints import Constraints


def test_constraint_add_and_check(benchmark):
    """Benchmark Constraints.add_constraint() and is_satisfied_by().

    This is a hot path - constraint checking happens thousands of times during
    dependency resolution. Measures:
    - Parsing constraint strings (e.g., "numpy>=1.20,<2.0")
    - Checking if versions satisfy constraints

    This benchmark uses stable Fromager APIs and works across all commits.
    """
    constraint_specs = [
        "numpy>=1.20,<2.0",
        "requests>=2.25",
        "packaging>=23.0",
        "pydantic>=2.0,<3.0",
        "torch>=2.0",
    ]

    def add_and_check():
        constraints = Constraints()
        for spec in constraint_specs:
            constraints.add_constraint(spec)

        # Check various versions
        results = []
        results.append(constraints.is_satisfied_by("numpy", Version("1.25.0")))
        results.append(constraints.is_satisfied_by("numpy", Version("2.0.0")))
        results.append(constraints.is_satisfied_by("requests", Version("2.28.0")))
        results.append(constraints.is_satisfied_by("pydantic", Version("1.10.0")))
        return results

    result = benchmark(add_and_check)
    # numpy 1.25.0 satisfies >=1.20,<2.0
    assert result[0] is True
    # numpy 2.0.0 does NOT satisfy >=1.20,<2.0
    assert result[1] is False
    # requests 2.28.0 satisfies >=2.25
    assert result[2] is True
    # pydantic 1.10.0 does NOT satisfy >=2.0,<3.0
    assert result[3] is False
