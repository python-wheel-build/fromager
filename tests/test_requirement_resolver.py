"""Tests for requirement_resolver module."""

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
from fromager.requirement_resolver import RequirementResolver
from fromager.requirements_file import RequirementType

# Test fixture: previous dependency graph
old_graph = DependencyGraph()

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("foo"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("foo"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr>=5"),
    req_version=Version("7"),
)

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("bar"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("bar"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr>=5,<7"),
    req_version=Version("6"),
)

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("blah"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("blah"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr==5"),
    req_version=Version("5"),
)


def test_resolve_from_graph_no_changes(tmp_context: WorkContext) -> None:
    """RequirementResolver resolves from previous graph with no changes."""
    resolver = RequirementResolver(tmp_context, old_graph)

    # Resolving new dependency that doesn't exist in graph
    assert (
        resolver._resolve_from_graph(
            req=Requirement("xyz"),
            req_type=RequirementType.INSTALL,
            pre_built=False,
            parent_req=Requirement("foo"),
        )
        is None
    )

    # Resolving pbr dependency of foo
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    ) == ("", Version("7"))

    # Resolving pbr dependency of bar
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == ("", Version("6"))

    # Resolving pbr dependency of blah
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_upgrade(tmp_context: WorkContext) -> None:
    """RequirementResolver prefers top-level requirements over history."""
    resolver = RequirementResolver(tmp_context, old_graph)

    # Simulating new bootstrap with a toplevel requirement of pbr==8
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr==8"),
        req_version=Version("8"),
    )

    # Resolving pbr dependency of foo - should get upgraded version from top-level
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    ) == ("", Version("8"))

    # Resolving pbr dependency of bar - constraint prevents upgrade
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == ("", Version("6"))

    # Resolving pbr dependency of blah - exact version requirement
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_downgrade(tmp_context: WorkContext) -> None:
    """RequirementResolver handles version downgrades from top-level requirements."""
    resolver = RequirementResolver(tmp_context, old_graph)

    # Simulating new bootstrap with a toplevel requirement of pbr<=6
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr<=6"),
        req_version=Version("6"),
    )

    # Resolving pbr dependency of foo - gets downgraded to 6
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    ) == ("", Version("6"))

    # Resolving pbr dependency of bar - already at 6
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == ("", Version("6"))

    # Resolving pbr dependency of blah - exact version requirement
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == ("", Version("5"))


def test_resolve_from_graph_toplevel_dep(tmp_context: WorkContext) -> None:
    """RequirementResolver resolves top-level dependencies correctly."""
    resolver = RequirementResolver(tmp_context, old_graph)

    # Simulating new bootstrap with a toplevel requirement for foo
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo==2"),
        req_version=Version("2"),
    )

    # Simulating new bootstrap with a toplevel requirement of bar (no change)
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("bar"),
        req_version=Version("1.0.0"),
    )

    # Resolving foo - should get new version from top-level
    assert resolver._resolve_from_graph(
        req=Requirement("foo==2"),
        req_type=RequirementType.TOP_LEVEL,
        pre_built=False,
        parent_req=None,
    ) == ("", Version("2"))

    # Resolving pbr dependency of foo even if foo version changed
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    ) == ("", Version("7"))

    # Resolving bar
    assert resolver._resolve_from_graph(
        req=Requirement("bar"),
        req_type=RequirementType.TOP_LEVEL,
        pre_built=False,
        parent_req=None,
    ) == ("", Version("1.0.0"))

    # Resolving pbr dependency of bar
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == ("", Version("6"))


def test_resolve_from_graph_no_previous_graph(tmp_context: WorkContext) -> None:
    """RequirementResolver returns None when no previous graph is available."""
    resolver = RequirementResolver(tmp_context, prev_graph=None)

    assert (
        resolver._resolve_from_graph(
            req=Requirement("pbr>=5"),
            req_type=RequirementType.INSTALL,
            pre_built=False,
            parent_req=Requirement("foo"),
        )
        is None
    )


def test_resolve_source_rejects_git_urls(tmp_context: WorkContext) -> None:
    """RequirementResolver.resolve_source() rejects git URLs."""
    resolver = RequirementResolver(tmp_context)

    with pytest.raises(
        ValueError, match="Git URL requirements must be handled by Bootstrapper"
    ):
        resolver.resolve_source(
            req=Requirement("package @ git+https://github.com/example/repo.git"),
            req_type=RequirementType.TOP_LEVEL,
            parent_req=None,
        )
