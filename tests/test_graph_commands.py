"""Test graph command functions that display constraint information."""

from unittest.mock import Mock

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import dependency_graph
from fromager.commands.graph import (
    _find_customized_dependencies_for_node,
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
