"""Benchmarks for Fromager resolution and parsing operations.

These benchmarks test actual Fromager code, not just external libraries.
Focus on pure Python, CPU-bound operations that don't require network
or subprocess calls.
"""
import pytest
from packaging.requirements import Requirement
from packaging.version import Version


# =============================================================================
# Constraints benchmarks (fromager.constraints)
# =============================================================================


def test_constraint_add_and_check(benchmark):
    """Benchmark Constraints.add_constraint() and is_satisfied_by().

    Tests the full constraint workflow: parsing constraint strings and
    checking version satisfaction.
    """
    from fromager.constraints import Constraints

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


def test_constraint_satisfaction_batch(benchmark):
    """Benchmark Constraints.is_satisfied_by() with many version checks.

    Focuses on the hot path of checking multiple versions against constraints.
    """
    from fromager.constraints import Constraints

    constraints = Constraints()
    constraints.add_constraint("numpy>=1.20,<2.0")

    versions = [Version(v) for v in [
        "1.19.0", "1.20.0", "1.21.0", "1.22.0", "1.23.0",
        "1.24.0", "1.25.0", "1.26.0", "2.0.0", "2.1.0",
    ]]

    def check_all():
        return [constraints.is_satisfied_by("numpy", v) for v in versions]

    result = benchmark(check_all)
    # 1.19.0 fails, 1.20.0-1.26.0 pass, 2.0.0+ fail
    assert result == [False, True, True, True, True, True, True, True, False, False]


def test_constraint_unconstrained_package(benchmark):
    """Benchmark is_satisfied_by() for packages without constraints.

    When no constraint exists, is_satisfied_by should return True immediately.
    This tests the fast path.
    """
    from fromager.constraints import Constraints

    constraints = Constraints()
    constraints.add_constraint("numpy>=1.20")

    versions = [Version(f"1.{i}.0") for i in range(100)]

    def check_unconstrained():
        # Check a package that has NO constraint - should always return True
        return [constraints.is_satisfied_by("requests", v) for v in versions]

    result = benchmark(check_unconstrained)
    assert all(result)


# =============================================================================
# DependencyGraph benchmarks (fromager.dependency_graph)
# =============================================================================


def test_graph_add_dependencies(benchmark):
    """Benchmark DependencyGraph.add_dependency() for building graphs.

    Tests the core operation of adding nodes and edges to the graph.
    """
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType

    def build_graph():
        graph = DependencyGraph()
        for i in range(50):
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=RequirementType.TOP_LEVEL,
                req=Requirement(f"pkg{i}>=1.0"),
                req_version=Version("1.0.0"),
            )
        return graph

    result = benchmark(build_graph)
    assert len(result) == 50


def test_graph_serialization(benchmark):
    """Benchmark DependencyGraph._to_dict() for JSON serialization.

    Tests the serialization path used when saving graphs to disk.
    """
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType

    # Pre-build a graph to benchmark only serialization
    graph = DependencyGraph()
    for i in range(50):
        graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(f"pkg{i}>=1.0"),
            req_version=Version("1.0.0"),
        )

    result = benchmark(graph._to_dict)
    # Should have 50 packages + 1 root node
    assert len(result) == 51


def test_graph_from_dict(benchmark):
    """Benchmark DependencyGraph.from_dict() for parsing graphs.

    Tests the deserialization path used when loading graphs from disk.
    """
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType

    # Pre-build a graph and serialize it
    source_graph = DependencyGraph()
    for i in range(50):
        source_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(f"pkg{i}>=1.0"),
            req_version=Version("1.0.0"),
        )
    graph_dict = source_graph._to_dict()

    def parse_graph():
        return DependencyGraph.from_dict(graph_dict)

    result = benchmark(parse_graph)
    assert len(result) == 50


@pytest.mark.slow
def test_graph_with_nested_deps(benchmark):
    """Benchmark graph operations with nested dependencies.

    Tests a more realistic scenario with parent-child relationships.
    """
    from packaging.utils import canonicalize_name
    from fromager.dependency_graph import DependencyGraph
    from fromager.requirements_file import RequirementType

    def build_nested_graph():
        graph = DependencyGraph()

        # Add top-level packages
        for i in range(10):
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=RequirementType.TOP_LEVEL,
                req=Requirement(f"top{i}>=1.0"),
                req_version=Version("1.0.0"),
            )

            # Each top-level has 5 install dependencies
            for j in range(5):
                graph.add_dependency(
                    parent_name=canonicalize_name(f"top{i}"),
                    parent_version=Version("1.0.0"),
                    req_type=RequirementType.INSTALL,
                    req=Requirement(f"dep{i}_{j}>=1.0"),
                    req_version=Version("1.0.0"),
                )

        return graph._to_dict()

    result = benchmark(build_nested_graph)
    # 10 top-level + 50 deps + 1 root = 61
    assert len(result) == 61


def test_topological_sorter_static_batches(benchmark):
    """Benchmark TrackingTopologicalSorter.static_batches().

    Tests the build order computation used for parallel builds.
    """
    from packaging.utils import canonicalize_name
    from fromager.dependency_graph import DependencyGraph, TrackingTopologicalSorter
    from fromager.requirements_file import RequirementType

    # Build a graph with some dependency structure
    graph = DependencyGraph()

    # Add base packages (no deps)
    for i in range(10):
        graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(f"base{i}>=1.0"),
            req_version=Version("1.0.0"),
        )

    # Create a simple topological sorter with the nodes
    def compute_batches():
        topo = TrackingTopologicalSorter()
        nodes = [n for n in graph.get_all_nodes() if n.key]  # Exclude root
        for node in nodes:
            topo.add(node)
        return list(topo.static_batches())

    result = benchmark(compute_batches)
    # All 10 nodes should be in batches
    total_nodes = sum(len(batch) for batch in result)
    assert total_nodes == 10


# =============================================================================
# Resolver benchmarks (fromager.resolver)
# =============================================================================


def test_python_version_matching_cold(benchmark):
    """Benchmark match_py_req() with cold cache.

    Tests the LRU-cached Python version matching with cache cleared.
    """
    from fromager.resolver import match_py_req

    specifiers = [
        ">=3.8",
        ">=3.9,<4.0",
        ">=3.10",
        "!=3.9.0",
        ">=3.8,!=3.9.1,<4.0",
        ">=3.11",
        ">=3.8,<3.12",
    ]

    def match_all_cold():
        # Clear cache to test cold performance
        match_py_req.cache_clear()
        return [match_py_req(s) for s in specifiers]

    benchmark(match_all_cold)


def test_python_version_matching_hot(benchmark):
    """Benchmark match_py_req() with hot cache.

    Tests cached performance - this is the typical production case
    where the same specifiers are checked repeatedly.
    """
    from fromager.resolver import match_py_req

    specifiers = [
        ">=3.8",
        ">=3.9,<4.0",
        ">=3.10",
        "!=3.9.0",
        ">=3.8,!=3.9.1,<4.0",
    ]

    # Warm the cache
    match_py_req.cache_clear()
    for s in specifiers:
        match_py_req(s)

    def match_all_hot():
        return [match_py_req(s) for s in specifiers]

    benchmark(match_all_hot)


@pytest.mark.slow
def test_python_version_matching_many_specifiers(benchmark):
    """Benchmark match_py_req() with many unique specifiers.

    Tests cache behavior with a large number of different specifiers.
    """
    from fromager.resolver import match_py_req

    # Generate many different specifiers
    specifiers = []
    for major in [3]:
        for minor in range(8, 15):
            specifiers.append(f">={major}.{minor}")
            specifiers.append(f"<{major}.{minor}")
            specifiers.append(f"=={major}.{minor}.*")

    def match_all():
        match_py_req.cache_clear()
        return [match_py_req(s) for s in specifiers]

    result = benchmark(match_all)
    assert len(result) == len(specifiers)


def test_base_provider_is_satisfied_by(benchmark):
    """Benchmark BaseProvider.is_satisfied_by() for candidate validation.

    Tests the core validation logic used during dependency resolution.
    """
    from fromager.constraints import Constraints
    from fromager.resolver import BaseProvider
    from fromager.candidate import Candidate

    constraints = Constraints()
    constraints.add_constraint("numpy>=1.20,<2.0")

    # Create a minimal concrete provider for testing
    class TestProvider(BaseProvider):
        provider_description = "test"

        @property
        def cache_key(self):
            return "test"

        def find_candidates(self, identifier):
            return []

    provider = TestProvider(constraints=constraints, use_resolver_cache=False)

    requirement = Requirement("numpy>=1.22")
    candidates = [
        Candidate(name="numpy", version=Version("1.21.0"), url=""),
        Candidate(name="numpy", version=Version("1.24.0"), url=""),
        Candidate(name="numpy", version=Version("1.25.0"), url=""),
        Candidate(name="numpy", version=Version("2.0.0"), url=""),
        Candidate(name="numpy", version=Version("1.19.0"), url=""),
    ]

    def check_all():
        return [provider.is_satisfied_by(requirement, c) for c in candidates]

    result = benchmark(check_all)
    # 1.21.0 fails (doesn't match >=1.22), 1.24/1.25 pass, 2.0 fails constraint, 1.19 fails both
    assert result == [False, True, True, False, False]
