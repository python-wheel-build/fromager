"""Test graph command functions that display constraint information."""

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import dependency_graph
from fromager.commands.graph import find_why, show_explain_duplicates
from fromager.requirements_file import RequirementType


def test_show_explain_duplicates_with_constraints(capsys):
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
        constraint="package-b>=1.0,<2.0",
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
        constraint="",
    )

    # Run the command
    show_explain_duplicates(graph)

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown at the package name level, not per-version
    assert "package-b (constraint: package-b>=1.0,<2.0)" in captured.out
    # Versions should be shown without constraint info
    assert "  1.0.0\n" in captured.out
    assert "  2.0.0\n" in captured.out
    # Version lines should not have constraint info
    assert "1.0.0 (constraint:" not in captured.out
    assert "2.0.0 (constraint:" not in captured.out


def test_find_why_with_constraints(capsys):
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
        constraint="parent-pkg==1.0.0",
    )

    # Add child dependency with its own constraint
    graph.add_dependency(
        parent_name=canonicalize_name("parent-pkg"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("child-pkg>=1.0"),
        req_version=Version("1.5.0"),
        download_url="https://example.com/child-pkg-1.5.0.tar.gz",
        constraint="child-pkg>=1.0,<2.0",
    )

    # Find why child-pkg is included
    child_node = graph.nodes["child-pkg==1.5.0"]
    find_why(graph, child_node, 1, 0, [])

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown for the child package at depth 0
    assert "child-pkg==1.5.0 (constraint: child-pkg>=1.0,<2.0)" in captured.out
    # Verify constraint is shown for the parent when showing the dependency relationship
    assert "(constraint: parent-pkg==1.0.0)" in captured.out


def test_find_why_toplevel_with_constraint(capsys):
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
        constraint="toplevel-pkg>=2.0,<3.0",
    )

    # Find why toplevel-pkg is included
    node = graph.nodes["toplevel-pkg==2.0.0"]
    find_why(graph, node, 0, 0, [])

    # Capture output
    captured = capsys.readouterr()

    # Verify constraint is shown at depth 0
    assert "toplevel-pkg==2.0.0 (constraint: toplevel-pkg>=2.0,<3.0)" in captured.out
    # Verify constraint is shown when identifying it as a top-level dependency
    assert (
        "toplevel-pkg==2.0.0 (constraint: toplevel-pkg>=2.0,<3.0) is a toplevel dependency"
        in captured.out
    )


def test_find_why_without_constraints(capsys):
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
