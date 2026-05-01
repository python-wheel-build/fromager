"""Test graph command functions that display constraint information."""

import json
import pathlib
from unittest.mock import Mock

import click
import pytest
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from fromager import dependency_graph
from fromager.commands.graph import (
    _compute_collection_impact,
    _find_customized_dependencies_for_node,
    _find_shared_packages,
    _get_collection_packages,
    _suggest_base_impl,
    find_why,
    show_explain_duplicates,
)
from fromager.requirements_file import RequirementType


def test_show_explain_duplicates_with_constraints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that explain_duplicates shows constraint information."""
    # Create a graph with duplicate dependencies that have constraints
    graph = dependency_graph.DependencyGraph()

    # Add top-level package
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )

    # Add package-b version 1.0.0 as dependency of package-a with constraint
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b>=1.0"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-b-1.0.0.tar.gz",
        constraint=Requirement("package-b>=1.0,<2.0"),
    )

    # Add another top-level package
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-c"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-c-1.0.0.tar.gz",
    )

    # Add package-b version 2.0.0 as dependency of package-c without constraint
    graph.add_dependency(
        parent_name=canonicalize_name("package-c"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b>=2.0"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/package-b-2.0.0.tar.gz",
        constraint=None,
    )

    # Run the command
    show_explain_duplicates(graph)

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown at the package name level, not per-version
    assert "package-b (constraint: package-b<2.0,>=1.0)" in captured.out
    # Versions should be shown without constraint info
    assert "  1.0.0\n" in captured.out
    assert "  2.0.0\n" in captured.out
    # Version lines should not have constraint info
    assert "1.0.0 (constraint:" not in captured.out
    assert "2.0.0 (constraint:" not in captured.out


def test_find_why_with_constraints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that why command shows constraint information."""
    # Create a graph with constraints
    graph = dependency_graph.DependencyGraph()

    # Add top-level package with constraint
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("parent-pkg"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/parent-pkg-1.0.0.tar.gz",
        constraint=Requirement("parent-pkg==1.0.0"),
    )

    # Add child dependency with its own constraint
    graph.add_dependency(
        parent_name=canonicalize_name("parent-pkg"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("child-pkg>=1.0"),
        req_version=Version("1.5.0"),
        download_url="https://example.com/child-pkg-1.5.0.tar.gz",
        constraint=Requirement("child-pkg>=1.0,<2.0"),
    )

    # Find why child-pkg is included
    child_node = graph.nodes["child-pkg==1.5.0"]
    find_why(graph, child_node, 1, 0, [])

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown for the child package at depth 0
    assert "child-pkg==1.5.0 (constraint: child-pkg<2.0,>=1.0)" in captured.out
    # Verify constraint is shown for the parent when showing the dependency relationship
    assert "(constraint: parent-pkg==1.0.0)" in captured.out


def test_find_why_toplevel_with_constraint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that why command shows constraint for top-level dependencies."""
    # Create a graph with a top-level package that has a constraint
    graph = dependency_graph.DependencyGraph()

    # Add top-level package with constraint
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("toplevel-pkg"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/toplevel-pkg-2.0.0.tar.gz",
        constraint=Requirement("toplevel-pkg<3.0,>=2.0"),
    )

    # Find why toplevel-pkg is included
    node = graph.nodes["toplevel-pkg==2.0.0"]
    find_why(graph, node, 0, 0, [])

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown at depth 0
    assert "toplevel-pkg==2.0.0 (constraint: toplevel-pkg<3.0,>=2.0)" in captured.out
    # Verify constraint is shown when identifying it as a top-level dependency
    assert (
        "toplevel-pkg==2.0.0 (constraint: toplevel-pkg<3.0,>=2.0) is a toplevel dependency"
        in captured.out
    )


def test_find_why_without_constraints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that why command works when no constraints are present."""
    # Create a graph without constraints
    graph = dependency_graph.DependencyGraph()

    # Add top-level package without constraint
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("simple-pkg"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/simple-pkg-1.0.0.tar.gz",
    )

    # Add child dependency without constraint
    graph.add_dependency(
        parent_name=canonicalize_name("simple-pkg"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("simple-child"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/simple-child-2.0.0.tar.gz",
    )

    # Find why simple-child is included
    child_node = graph.nodes["simple-child==2.0.0"]
    find_why(graph, child_node, 1, 0, [])

    # Capture output
    captured = capsys.readouterr()

    # Verify no constraint info is shown
    assert "(constraint:" not in captured.out
    assert "simple-child==2.0.0" in captured.out
    assert "simple-pkg==1.0.0" in captured.out


def test_find_direct_customized_dependency() -> None:
    """Test finding a direct child with customizations."""
    # Setup: A -> B (customized)
    graph = dependency_graph.DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b>=1.0"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/package-b-2.0.0.tar.gz",
    )

    # Mock context to mark package-b as customized
    mock_ctx = Mock()
    mock_settings = Mock()

    def mock_pbi(name: str) -> Mock:
        pbi = Mock()
        pbi.has_customizations = name == "package-b"
        return pbi

    mock_settings.package_build_info = mock_pbi
    mock_ctx.settings = mock_settings

    # Test
    node_a = graph.nodes["package-a==1.0.0"]
    result = _find_customized_dependencies_for_node(
        mock_ctx, node_a, install_only=False
    )

    # Verify
    assert len(result) == 1
    assert "package-b==2.0.0" in result
    assert result["package-b==2.0.0"] == "package-b>=1.0"


def test_find_transitive_customized_dependency() -> None:
    """Test finding customized dependency through non-customized intermediate."""
    # Setup: A -> B (not customized) -> C (customized)
    graph = dependency_graph.DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b>=1.0"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/package-b-2.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-b"),
        parent_version=Version("2.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c"),
        req_version=Version("3.0.0"),
        download_url="https://example.com/package-c-3.0.0.tar.gz",
    )

    # Mock context: only package-c is customized
    mock_ctx = Mock()
    mock_settings = Mock()

    def mock_pbi(name: str) -> Mock:
        pbi = Mock()
        pbi.has_customizations = name == "package-c"
        return pbi

    mock_settings.package_build_info = mock_pbi
    mock_ctx.settings = mock_settings

    # Test
    node_a = graph.nodes["package-a==1.0.0"]
    result = _find_customized_dependencies_for_node(
        mock_ctx, node_a, install_only=False
    )

    # Verify: Should find C (not B), with A's original requirement
    assert len(result) == 1
    assert "package-c==3.0.0" in result
    assert result["package-c==3.0.0"] == "package-b>=1.0"  # A's requirement, not B's


def test_install_only_skips_build_dependencies() -> None:
    """Test that install_only=True skips build dependencies."""
    # Setup: A -> B (build dep, customized)
    graph = dependency_graph.DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.BUILD_BACKEND,  # Build dependency
        req=Requirement("package-b"),
        req_version=Version("2.0.0"),
        download_url="https://example.com/package-b-2.0.0.tar.gz",
    )

    # Mock context: package-b is customized
    mock_ctx = Mock()
    mock_settings = Mock()

    def mock_pbi(name: str) -> Mock:
        pbi = Mock()
        pbi.has_customizations = name == "package-b"
        return pbi

    mock_settings.package_build_info = mock_pbi
    mock_ctx.settings = mock_settings

    # Test with install_only=True
    node_a = graph.nodes["package-a==1.0.0"]
    result = _find_customized_dependencies_for_node(mock_ctx, node_a, install_only=True)

    # Verify: Should be empty (build dep skipped)
    assert len(result) == 0


def test_cycle_prevention_no_infinite_loop() -> None:
    """Test that circular dependencies don't cause infinite loops."""
    # Setup: A -> B -> C -> A (cycle)
    graph = dependency_graph.DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-b-1.0.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("package-b"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-c-1.0.0.tar.gz",
    )
    # Create cycle: C -> A
    graph.add_dependency(
        parent_name=canonicalize_name("package-c"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )

    # Mock context: only package-c is customized
    mock_ctx = Mock()
    mock_settings = Mock()

    def mock_pbi(name: str) -> Mock:
        pbi = Mock()
        pbi.has_customizations = name == "package-c"
        return pbi

    mock_settings.package_build_info = mock_pbi
    mock_ctx.settings = mock_settings

    # Test: Should not hang or raise error
    node_a = graph.nodes["package-a==1.0.0"]
    result = _find_customized_dependencies_for_node(
        mock_ctx, node_a, install_only=False
    )

    # Verify: Should find C once, despite cycle
    assert len(result) == 1
    assert "package-c==1.0.0" in result


def test_requirement_preservation_through_chain() -> None:
    """Test that original requirement is preserved through dependency chain."""
    # Setup: A requires "package-b>=1.0,<2.0"
    #        A -> B -> C (customized)
    graph = dependency_graph.DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/package-a-1.0.0.tar.gz",
    )
    # A's requirement of B is specific
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-b>=1.0,<2.0"),
        req_version=Version("1.5.0"),
        download_url="https://example.com/package-b-1.5.0.tar.gz",
    )
    # B's requirement of C is different
    graph.add_dependency(
        parent_name=canonicalize_name("package-b"),
        parent_version=Version("1.5.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=3.0"),
        req_version=Version("3.5.0"),
        download_url="https://example.com/package-c-3.5.0.tar.gz",
    )

    # Mock context: only package-c is customized
    mock_ctx = Mock()
    mock_settings = Mock()

    def mock_pbi(name: str) -> Mock:
        pbi = Mock()
        pbi.has_customizations = name == "package-c"
        return pbi

    mock_settings.package_build_info = mock_pbi
    mock_ctx.settings = mock_settings

    # Test
    node_a = graph.nodes["package-a==1.0.0"]
    result = _find_customized_dependencies_for_node(
        mock_ctx, node_a, install_only=False
    )

    # Verify: Should preserve A's original requirement, not B's
    assert len(result) == 1
    assert "package-c==3.5.0" in result
    # Should be A's requirement of B (the first in the chain), not B's requirement of C
    # Note: The packaging library may normalize the requirement string order
    requirement_str = result["package-c==3.5.0"]
    assert "package-b" in requirement_str
    assert ">=1.0" in requirement_str or ">= 1.0" in requirement_str
    assert "<2.0" in requirement_str or "< 2.0" in requirement_str
    # Should NOT be B's requirement of C
    assert "package-c" not in requirement_str


# ---------------------------------------------------------------------------
# Helpers for suggest_base tests
# ---------------------------------------------------------------------------


def _make_graph_file(tmp_path: pathlib.Path, stem: str, packages: list[str]) -> str:
    """Write a minimal graph JSON file containing the given top-level packages."""
    graph = dependency_graph.DependencyGraph()
    for pkg in packages:
        graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(pkg),
            req_version=Version("1.0.0"),
            download_url=f"https://example.com/{pkg}-1.0.0.tar.gz",
        )
    path = tmp_path / f"{stem}.json"
    with open(path, "w") as f:
        graph.serialize(f)
    return str(path)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_get_collection_packages(tmp_path: pathlib.Path) -> None:
    """_get_collection_packages returns normalized names, excluding ROOT."""
    path = _make_graph_file(tmp_path, "col-a", ["package-one", "PackageTwo"])
    result = _get_collection_packages(path)
    assert NormalizedName("package-one") in result
    assert NormalizedName("packagetwo") in result
    assert NormalizedName("") not in result  # ROOT excluded


def test_find_shared_packages_basic() -> None:
    """Basic overlap: packages in >= 2 of 3 collections are returned."""
    collections: dict[str, set[NormalizedName]] = {
        "a": {NormalizedName("b"), NormalizedName("c"), NormalizedName("d")},
        "b": {NormalizedName("b"), NormalizedName("c"), NormalizedName("e")},
        "c": {NormalizedName("c"), NormalizedName("f")},
    }
    results = _find_shared_packages(collections, min_collections=2)
    packages = {r["package"] for r in results}
    assert NormalizedName("b") in packages
    assert NormalizedName("c") in packages
    assert NormalizedName("d") not in packages  # only in 1
    assert NormalizedName("e") not in packages  # only in 1
    assert NormalizedName("f") not in packages  # only in 1


def test_find_shared_packages_threshold() -> None:
    """min_collections=3 returns only packages in all 3 collections."""
    collections: dict[str, set[NormalizedName]] = {
        "a": {NormalizedName("b"), NormalizedName("c"), NormalizedName("d")},
        "b": {
            NormalizedName("b"),
            NormalizedName("c"),
            NormalizedName("d"),
            NormalizedName("e"),
        },
        "c": {NormalizedName("c"), NormalizedName("d"), NormalizedName("f")},
    }
    results = _find_shared_packages(collections, min_collections=3)
    packages = {r["package"] for r in results}
    assert NormalizedName("c") in packages
    assert NormalizedName("d") in packages
    assert NormalizedName("b") not in packages  # only in 2


def test_find_shared_packages_sorting() -> None:
    """Results sorted by count desc then package name asc."""
    collections: dict[str, set[NormalizedName]] = {
        "a": {NormalizedName("z"), NormalizedName("m"), NormalizedName("a")},
        "b": {NormalizedName("z"), NormalizedName("m"), NormalizedName("a")},
        "c": {NormalizedName("z")},
    }
    results = _find_shared_packages(collections, min_collections=2)
    # z is in 3 collections, m and a in 2
    assert results[0]["package"] == NormalizedName("z")
    # Among count=2 entries, 'a' comes before 'm'
    remaining = [r["package"] for r in results[1:]]
    assert remaining == sorted(remaining)


# ---------------------------------------------------------------------------
# Command output tests
# ---------------------------------------------------------------------------


def test_suggest_base_table_output(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """suggest_base command produces table output with key strings."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-only-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=None,
        min_collections=2,
        output_format="table",
    )

    captured = capsys.readouterr()
    assert "pkg-shared" in captured.out
    assert "Total unique packages: 3" in captured.out
    assert "Packages in >= 2 collections: 1" in captured.out
    # pkg-only-* appear in the Remaining Packages section, not the candidates table
    assert "pkg-only-a" in captured.out
    assert "pkg-only-b" in captured.out


def test_suggest_base_dynamic_default_min_collections(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """Default --min-collections is 50% of provided graphs (rounded up)."""
    # 4 graphs → default threshold = ceil(4/2) = 2
    # pkg-shared-ab is in A and B (2/4), pkg-shared-abc is in A, B, C (3/4)
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared-ab", "pkg-shared-abc"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared-ab", "pkg-shared-abc"])
    path_c = _make_graph_file(tmp_path, "coll-c", ["pkg-shared-abc"])
    path_d = _make_graph_file(tmp_path, "coll-d", ["pkg-only-d"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b, path_c, path_d),
        base_graph=None,
        min_collections=None,  # dynamic default: ceil(4/2) = 2
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["metadata"]["min_collections"] == 2
    packages = {c["package"] for c in data["candidates"]}
    assert "pkg-shared-ab" in packages
    assert "pkg-shared-abc" in packages
    assert "pkg-only-d" not in packages


def test_suggest_base_json_output(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """suggest_base command produces valid JSON output."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-only-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=None,
        min_collections=2,
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "metadata" in data
    assert "candidates" in data
    assert data["metadata"]["total_collections"] == 2
    assert data["metadata"]["total_unique_packages"] == 3
    assert data["metadata"]["packages_meeting_threshold"] == 1
    assert data["metadata"]["min_collections"] == 2
    assert len(data["candidates"]) == 1
    candidate = data["candidates"][0]
    assert candidate["package"] == "pkg-shared"
    assert candidate["collection_count"] == 2
    assert candidate["coverage_percentage"] == 100.0
    assert "in_base" not in candidate


def test_suggest_base_with_base_graph(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """--base flag marks packages that are already in the base graph."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-new"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-new"])
    path_base = _make_graph_file(tmp_path, "base", ["pkg-shared"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=path_base,
        min_collections=2,
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    candidates_by_pkg = {c["package"]: c for c in data["candidates"]}
    assert candidates_by_pkg["pkg-shared"]["in_base"] is True
    assert candidates_by_pkg["pkg-new"]["in_base"] is False
    assert data["metadata"]["base_graph"] == path_base


def test_suggest_base_too_few_graphs(tmp_path: pathlib.Path) -> None:
    """Error raised when fewer than 2 graphs are provided."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-a"])

    with pytest.raises(click.UsageError, match="At least 2 collection graphs"):
        _suggest_base_impl(
            collection_graphs=(path_a,),
            base_graph=None,
            min_collections=2,
            output_format="table",
        )


def test_suggest_base_invalid_min_collections(tmp_path: pathlib.Path) -> None:
    """Error raised when --min-collections exceeds number of graphs."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-b"])

    with pytest.raises(click.UsageError, match="cannot exceed number of graphs"):
        _suggest_base_impl(
            collection_graphs=(path_a, path_b),
            base_graph=None,
            min_collections=3,
            output_format="table",
        )


# ---------------------------------------------------------------------------
# Tests for _compute_collection_impact
# ---------------------------------------------------------------------------


def test_compute_collection_impact_basic() -> None:
    """Remaining counts and per-package cross-collection counts are correct."""
    # Arrange: 3 collections with known overlap
    # base candidates: pkg-shared (in all 3)
    # remaining: pkg-ab (in a, b), pkg-only-a (in a only), etc.
    collections: dict[str, set[NormalizedName]] = {
        "coll-a": {
            NormalizedName("pkg-shared"),
            NormalizedName("pkg-ab"),
            NormalizedName("pkg-only-a"),
        },
        "coll-b": {
            NormalizedName("pkg-shared"),
            NormalizedName("pkg-ab"),
            NormalizedName("pkg-only-b"),
        },
        "coll-c": {
            NormalizedName("pkg-shared"),
            NormalizedName("pkg-only-c"),
        },
    }
    base_package_names: set[NormalizedName] = {NormalizedName("pkg-shared")}

    # Act
    result = _compute_collection_impact(collections, base_package_names)

    # Assert: each collection entry has correct counts
    by_coll = {entry["collection"]: entry for entry in result}
    assert by_coll["coll-a"]["total_packages"] == 3
    assert by_coll["coll-a"]["base_packages"] == 1
    assert by_coll["coll-a"]["remaining_packages"] == 2
    assert by_coll["coll-b"]["remaining_packages"] == 2
    assert by_coll["coll-c"]["remaining_packages"] == 1

    # pkg-ab appears in 2 collections, should have collection_count=2
    coll_a_remaining = {r["package"]: r for r in by_coll["coll-a"]["remaining"]}
    assert coll_a_remaining[NormalizedName("pkg-ab")]["collection_count"] == 2
    assert coll_a_remaining[NormalizedName("pkg-only-a")]["collection_count"] == 1

    # reduction_percentage for coll-a: 1/3 * 100 = 33.3%
    assert by_coll["coll-a"]["reduction_percentage"] == 33.3


def test_compute_collection_impact_sorting() -> None:
    """Results sorted by remaining_packages desc, then collection name asc."""
    collections: dict[str, set[NormalizedName]] = {
        "coll-z": {NormalizedName("pkg-shared"), NormalizedName("r1")},
        "coll-a": {
            NormalizedName("pkg-shared"),
            NormalizedName("r2"),
            NormalizedName("r3"),
        },
        "coll-m": {NormalizedName("pkg-shared")},
    }
    base_package_names: set[NormalizedName] = {NormalizedName("pkg-shared")}

    result = _compute_collection_impact(collections, base_package_names)

    # coll-a has 2 remaining, coll-z has 1, coll-m has 0
    assert result[0]["collection"] == "coll-a"
    assert result[1]["collection"] == "coll-z"
    assert result[2]["collection"] == "coll-m"


def test_suggest_base_table_includes_impact(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """Table output includes Collection Impact section."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-only-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=None,
        min_collections=2,
        output_format="table",
    )

    captured = capsys.readouterr()
    assert "Collection Impact" in captured.out
    assert "Total Pkgs" in captured.out
    assert "In Base" in captured.out
    assert "Remaining" in captured.out
    assert "% Saved" in captured.out
    # Title may be word-wrapped by Rich; check for the prefix
    assert "Remaining Packages (not in proposed" in captured.out


def test_suggest_base_json_includes_impact(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """JSON output includes collection_impact key with correct structure."""
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-only-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=None,
        min_collections=2,
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "collection_impact" in data
    impact = data["collection_impact"]
    assert len(impact) == 2

    by_coll = {entry["collection"]: entry for entry in impact}
    # Each collection has 2 total packages, 1 shared (in base), 1 remaining
    for coll_name in ("coll-a", "coll-b"):
        entry = by_coll[coll_name]
        assert entry["total_packages"] == 2
        assert entry["base_packages"] == 1
        assert entry["remaining_packages"] == 1
        assert entry["reduction_percentage"] == 50.0
        assert len(entry["remaining"]) == 1


def test_suggest_base_json_base_only_packages(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """Packages in --base that are not candidates appear in base_only_packages."""
    # pkg-shared is a candidate (in both collections); pkg-base-only is only in the base
    path_a = _make_graph_file(tmp_path, "coll-a", ["pkg-shared", "pkg-only-a"])
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])
    path_base = _make_graph_file(tmp_path, "base", ["pkg-shared", "pkg-base-only"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=path_base,
        min_collections=2,
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # pkg-base-only is in the base but not a candidate
    assert "base_only_packages" in data
    assert "pkg-base-only" in data["base_only_packages"]
    # pkg-shared is a candidate and in the base; it should NOT be in base_only_packages
    assert "pkg-shared" not in data["base_only_packages"]


def test_suggest_base_json_base_only_impacts_collection_impact(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """Base-only packages count toward collection impact when --base is provided."""
    # pkg-shared is a candidate; pkg-base-only is base-only but appears in coll-a
    path_a = _make_graph_file(
        tmp_path, "coll-a", ["pkg-shared", "pkg-base-only", "pkg-only-a"]
    )
    path_b = _make_graph_file(tmp_path, "coll-b", ["pkg-shared", "pkg-only-b"])
    path_base = _make_graph_file(tmp_path, "base", ["pkg-shared", "pkg-base-only"])

    _suggest_base_impl(
        collection_graphs=(path_a, path_b),
        base_graph=path_base,
        min_collections=2,
        output_format="json",
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    by_coll = {entry["collection"]: entry for entry in data["collection_impact"]}
    # coll-a has 3 packages; pkg-shared and pkg-base-only are both in the proposed
    # base, so base_packages=2 and remaining_packages=1
    assert by_coll["coll-a"]["base_packages"] == 2
    assert by_coll["coll-a"]["remaining_packages"] == 1
    # coll-b has 2 packages; only pkg-shared is in the proposed base
    assert by_coll["coll-b"]["base_packages"] == 1
    assert by_coll["coll-b"]["remaining_packages"] == 1
