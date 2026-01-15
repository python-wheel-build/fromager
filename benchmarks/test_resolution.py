"""
Benchmarks for Fromager resolution and parsing operations.

These benchmarks test actual Fromager code using direct API calls only.
No custom logic or synthetic reimplementations - benchmarks fail if
Fromager's API changes.

Focus on pure Python, CPU-bound operations that don't require network
or subprocess calls.
"""

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


def test_topological_sorter_static_batches(benchmark):
    """Benchmark TrackingTopologicalSorter.static_batches().

    Tests the build order computation used for parallel builds.
    """
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
