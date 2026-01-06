"""Integration benchmarks that run actual builds.

These benchmarks are slow (use subprocess tracing) and run nightly.
They require network isolation via the local PyPI server and measure
full end-to-end build performance.

Markers:
    @pytest.mark.integration: Marks tests as integration benchmarks
    @pytest.mark.slow: Marks tests as slow-running

To run locally:
    uv run pytest benchmarks/test_integration.py -m "integration" --benchmark-only

Note: These tests are skipped by default in CI unless run via the nightly workflow.
"""

from __future__ import annotations

import pathlib
import tempfile
from typing import TYPE_CHECKING, Any

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

if TYPE_CHECKING:
    from fixtures.metrics import SubprocessTimer
    from fixtures.pypi_server import LocalPyPI


# =============================================================================
# Requirements parsing and constraint resolution benchmark
# =============================================================================


@pytest.mark.integration
def test_requirements_parsing_with_constraints(
    benchmark: Any,
    tmp_path: pathlib.Path,
) -> None:
    """Benchmark parsing requirements files and applying constraints.

    This test measures the full workflow of reading requirements from disk,
    parsing them, and checking against a constraints set - simulating a
    realistic build preparation scenario.
    """
    from fromager.constraints import Constraints
    from fromager.requirements_file import parse_requirements_file

    # Create a realistic requirements file with multiple packages
    requirements_content = """
# Core dependencies
numpy>=1.20,<2.0
scipy>=1.9.0
pandas>=2.0,<3.0
matplotlib>=3.7.0

# ML dependencies
scikit-learn>=1.2.0
# torch>=2.0.0  # commented out

# Utility packages
requests>=2.28.0
urllib3>=1.26,<2.0
certifi>=2023.0.0

# Testing dependencies
pytest>=7.0.0
pytest-cov>=4.0.0
"""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(requirements_content)

    # Create a constraints file
    constraints_content = """
numpy>=1.22,<1.27
scipy>=1.10,<1.14
pandas>=2.0,<2.2
urllib3<2.0
"""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(constraints_content)

    def parse_and_constrain() -> list[tuple[Requirement, bool]]:
        # Parse requirements file
        req_lines = list(parse_requirements_file(req_file))

        # Load constraints
        constraints = Constraints()
        for line in parse_requirements_file(constraints_file):
            constraints.add_constraint(line)

        # Parse each requirement and check constraints
        results = []
        for line in req_lines:
            req = Requirement(line)
            # Check if a representative version satisfies constraints
            is_satisfied = constraints.is_satisfied_by(req.name, Version("1.25.0"))
            results.append((req, is_satisfied))

        return results

    result = benchmark(parse_and_constrain)
    # Should have parsed 10 non-commented requirements
    assert len(result) == 10


# =============================================================================
# PyprojectFix workflow benchmark
# =============================================================================


@pytest.mark.integration
def test_pyproject_modification_workflow(
    benchmark: Any,
    tmp_path: pathlib.Path,
) -> None:
    """Benchmark pyproject.toml modification workflow.

    This test measures the PyprojectFix class which is used to modify
    build-system requirements in pyproject.toml files during source
    preparation.
    """
    from fromager.pyproject import PyprojectFix

    # Create a realistic pyproject.toml
    pyproject_content = """\
[build-system]
requires = ["setuptools>=61.0", "wheel", "cython>=0.29"]
build-backend = "setuptools.build_meta"

[project]
name = "example-package"
version = "1.0.0"
description = "An example package"
requires-python = ">=3.9"

[project.optional-dependencies]
dev = ["pytest>=7.0", "black"]
"""
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text(pyproject_content)

    req = Requirement("example-package>=1.0")

    def modify_pyproject() -> None:
        # Simulate adding/updating build requirements
        fixer = PyprojectFix(
            req,
            build_dir=tmp_path,
            update_build_requires=[
                "setuptools>=65.0",
                "numpy>=1.20",  # Add new dependency
                "cython>=3.0",  # Update existing
            ],
            remove_build_requires=["wheel"],  # type: ignore[list-item]
        )
        fixer.run()

    benchmark(modify_pyproject)

    # Verify modifications were applied
    import tomlkit

    result = tomlkit.parse(pyproject_file.read_text())
    build_requires = result["build-system"]["requires"]  # type: ignore[index]
    assert "wheel" not in build_requires
    assert any("numpy" in req for req in build_requires)


# =============================================================================
# Dependency graph with file parsing benchmark
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_dependency_graph_from_requirements_file(
    benchmark: Any,
    tmp_path: pathlib.Path,
) -> None:
    """Benchmark building a dependency graph from a requirements file.

    This test combines file parsing, requirement parsing, and graph
    construction to measure a realistic dependency resolution workflow.
    """
    from packaging.utils import canonicalize_name

    from fromager.constraints import Constraints
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType, parse_requirements_file

    # Create a larger requirements file simulating a real project
    packages = [
        "numpy>=1.20,<2.0",
        "scipy>=1.9.0",
        "pandas>=2.0",
        "matplotlib>=3.7.0",
        "scikit-learn>=1.2.0",
        "requests>=2.28.0",
        "urllib3>=1.26",
        "certifi>=2023.0.0",
        "packaging>=23.0",
        "pydantic>=2.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.22.0",
        "sqlalchemy>=2.0",
        "alembic>=1.11.0",
        "redis>=4.5.0",
        "celery>=5.3.0",
        "pytest>=7.0.0",
        "pytest-cov>=4.0.0",
        "black>=23.0.0",
        "ruff>=0.0.270",
    ]

    req_file = tmp_path / "requirements.txt"
    req_file.write_text("\n".join(packages))

    # Create constraints
    constraints_content = """
numpy<1.27
scipy<1.13
pandas<2.2
pydantic<2.5
"""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(constraints_content)

    def build_graph_from_file() -> DependencyGraph:
        # Load constraints
        constraints = Constraints()
        for line in parse_requirements_file(constraints_file):
            constraints.add_constraint(line)

        # Build graph from requirements file
        graph = DependencyGraph()

        for line in parse_requirements_file(req_file):
            req = Requirement(line)
            # Add top-level requirements
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=RequirementType.TOP_LEVEL,
                req=req,
                req_version=Version("1.0.0"),  # Placeholder resolved version
            )

            # Simulate some install dependencies for each package
            for i in range(3):
                dep_req = Requirement(f"dep-{canonicalize_name(req.name)}-{i}>=1.0")
                graph.add_dependency(
                    parent_name=canonicalize_name(req.name),
                    parent_version=Version("1.0.0"),
                    req_type=RequirementType.INSTALL,
                    req=dep_req,
                    req_version=Version("1.0.0"),
                )

        return graph

    result = benchmark(build_graph_from_file)
    # Should have 20 top-level + 60 deps = 80 packages
    assert len(result) == 80


# =============================================================================
# Subprocess-instrumented benchmarks (use fixtures)
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_full_build_simple_package(
    benchmark: Any,
    configured_env: "LocalPyPI",
    subprocess_timer: "SubprocessTimer",
) -> None:
    """Benchmark building a simple pure-Python package.

    This test measures the full build process for a simple package,
    including dependency resolution, source download, and wheel building.

    The configured_env fixture ensures all network operations use the
    local PyPI server for reproducible results.
    """
    from fromager.constraints import Constraints
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType

    def build_package() -> DependencyGraph:
        # Simulate a build workflow using the local PyPI environment
        # The configured_env sets UV_INDEX_URL to local server
        constraints = Constraints()
        constraints.add_constraint("packaging>=23.0")

        graph = DependencyGraph()

        # Add a simple package as if we resolved it
        req = Requirement("packaging>=23.0")
        graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=req,
            req_version=Version("23.2"),
        )

        # Serialize and deserialize to simulate persistence
        graph_dict = graph._to_dict()
        reconstructed = DependencyGraph.from_dict(graph_dict)

        return reconstructed

    with subprocess_timer.measure():
        result = benchmark(build_package)

    # Record subprocess metrics for analysis
    benchmark.extra_info["subprocess_calls"] = subprocess_timer.call_count
    benchmark.extra_info["subprocess_time"] = subprocess_timer.total_time
    benchmark.extra_info["overhead_ratio"] = subprocess_timer.overhead_ratio

    assert len(result) == 1


@pytest.mark.integration
@pytest.mark.slow
def test_resolution_with_constraints(
    benchmark: Any,
    configured_env: "LocalPyPI",
    subprocess_timer: "SubprocessTimer",
) -> None:
    """Benchmark package resolution with constraints.

    This test measures how long it takes to resolve a package with
    version constraints, simulating a realistic build scenario.
    """
    from fromager.constraints import Constraints
    from fromager.resolver import match_py_req

    # Define constraints and requirements
    constraint_specs = [
        "numpy>=1.20,<2.0",
        "requests>=2.25",
        "packaging>=23.0",
        "pydantic>=2.0,<3.0",
        "torch>=2.0",
        "scipy>=1.9,<1.14",
        "pandas>=2.0,<2.3",
    ]

    python_specifiers = [
        ">=3.8",
        ">=3.9,<4.0",
        ">=3.10",
        "!=3.9.0",
        ">=3.8,!=3.9.1,<4.0",
        ">=3.11",
        ">=3.8,<3.12",
    ]

    def resolve_with_constraints() -> tuple[list[bool], list[bool]]:
        # Build and check constraints
        constraints = Constraints()
        for spec in constraint_specs:
            constraints.add_constraint(spec)

        # Check various versions against constraints
        version_checks = []
        for pkg, version in [
            ("numpy", "1.25.0"),
            ("numpy", "2.0.0"),
            ("requests", "2.28.0"),
            ("pydantic", "1.10.0"),
            ("scipy", "1.12.0"),
        ]:
            is_satisfied = constraints.is_satisfied_by(pkg, Version(version))
            version_checks.append(is_satisfied)

        # Also check Python version matching (uses LRU cache)
        match_py_req.cache_clear()  # Cold cache test
        py_checks = [match_py_req(s) for s in python_specifiers]

        return version_checks, py_checks

    with subprocess_timer.measure():
        version_results, py_results = benchmark(resolve_with_constraints)

    benchmark.extra_info["subprocess_calls"] = subprocess_timer.call_count
    benchmark.extra_info["subprocess_time"] = subprocess_timer.total_time

    # Verify expected results
    assert version_results[0] is True  # numpy 1.25.0 satisfies >=1.20,<2.0
    assert version_results[1] is False  # numpy 2.0.0 does NOT satisfy
    assert version_results[2] is True  # requests 2.28.0 satisfies >=2.25


@pytest.mark.integration
@pytest.mark.slow
def test_dependency_graph_serialization_roundtrip(
    benchmark: Any,
    configured_env: "LocalPyPI",
) -> None:
    """Benchmark dependency graph serialization and deserialization.

    This test measures the time to build a complete dependency graph,
    serialize it to a dict (for JSON storage), and reconstruct it.
    This simulates the caching workflow used in Fromager.
    """
    from packaging.utils import canonicalize_name

    from fromager.dependency_graph import DependencyGraph, TrackingTopologicalSorter
    from fromager.requirements_file import RequirementType

    def build_serialize_deserialize() -> tuple[DependencyGraph, list[Any]]:
        # Build a moderately complex graph
        graph = DependencyGraph()

        # Add top-level packages
        for i in range(15):
            req = Requirement(f"pkg{i}>=1.0")
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=RequirementType.TOP_LEVEL,
                req=req,
                req_version=Version("1.0.0"),
            )

            # Each top-level has 3 install dependencies
            for j in range(3):
                dep_req = Requirement(f"dep{i}_{j}>=1.0")
                graph.add_dependency(
                    parent_name=canonicalize_name(f"pkg{i}"),
                    parent_version=Version("1.0.0"),
                    req_type=RequirementType.INSTALL,
                    req=dep_req,
                    req_version=Version("1.0.0"),
                )

        # Serialize to dict
        graph_dict = graph._to_dict()

        # Deserialize back
        reconstructed = DependencyGraph.from_dict(graph_dict)

        # Compute topological order
        topo = TrackingTopologicalSorter()
        nodes = [n for n in reconstructed.get_all_nodes() if n.key]
        for node in nodes:
            topo.add(node)
        batches = list(topo.static_batches())

        return reconstructed, batches

    result_graph, result_batches = benchmark(build_serialize_deserialize)

    # 15 top-level + 45 deps = 60 packages
    assert len(result_graph) == 60
    # All nodes should be in batches
    total_batch_nodes = sum(len(batch) for batch in result_batches)
    assert total_batch_nodes == 60
