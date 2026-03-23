"""Tests for requirement_resolver module."""

from unittest.mock import MagicMock, patch

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
    ) == [("", Version("7"))]

    # Resolving pbr dependency of bar
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == [("", Version("6"))]

    # Resolving pbr dependency of blah
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == [("", Version("5"))]


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
    ) == [("", Version("8"))]

    # Resolving pbr dependency of bar - constraint prevents upgrade
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == [("", Version("6"))]

    # Resolving pbr dependency of blah - exact version requirement
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == [("", Version("5"))]


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
    ) == [("", Version("6"))]

    # Resolving pbr dependency of bar - already at 6
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == [("", Version("6"))]

    # Resolving pbr dependency of blah - exact version requirement
    assert resolver._resolve_from_graph(
        req=Requirement("pbr==5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("blah"),
    ) == [("", Version("5"))]


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
    ) == [("", Version("2"))]

    # Resolving pbr dependency of foo even if foo version changed
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    ) == [("", Version("7"))]

    # Resolving bar
    assert resolver._resolve_from_graph(
        req=Requirement("bar"),
        req_type=RequirementType.TOP_LEVEL,
        pre_built=False,
        parent_req=None,
    ) == [("", Version("1.0.0"))]

    # Resolving pbr dependency of bar
    assert resolver._resolve_from_graph(
        req=Requirement("pbr>=5,<7"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("bar"),
    ) == [("", Version("6"))]


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


def test_resolve_from_graph_new_parent_reuses_existing_version(
    tmp_context: WorkContext,
) -> None:
    """Graph resolution finds a package even when encountered via a new parent.

    In a repeatable build, packaging==25.0 exists in the previous graph
    under setuptools-scm.  A new dependency (wheel) also requires packaging>=24.0.
    Because wheel is not in the previous graph, the parent-specific lookup fails
    and fromager falls back to PyPI, picking up packaging==26.0 instead of reusing 25.0.
    """
    # Build a previous graph that mirrors the real-world scenario:
    # ROOT -> setuptools-scm==9.2.2 --[install]--> packaging==25.0
    prev_graph = DependencyGraph()
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("setuptools-scm"),
        req_version=Version("9.2.2"),
    )
    prev_graph.add_dependency(
        parent_name=canonicalize_name("setuptools-scm"),
        parent_version=Version("9.2.2"),
        req_type=RequirementType.INSTALL,
        req=Requirement("packaging>=20"),
        req_version=Version("25.0"),
    )

    resolver = RequirementResolver(tmp_context, prev_graph)

    # Resolve packaging>=24.0 via a NEW parent "wheel" that is NOT in prev_graph.
    # packaging==25.0 satisfies >=24.0 and exists in the graph, so it should
    # be returned instead of falling back to PyPI.
    result = resolver._resolve_from_graph(
        req=Requirement("packaging>=24.0"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("wheel"),
    )
    assert result is not None, (
        "Expected packaging==25.0 from prev_graph but got None (would fall back to PyPI)"
    )
    assert result == [("", Version("25.0"))]


def test_resolve_from_graph_different_req_type_reuses_existing_version(
    tmp_context: WorkContext,
) -> None:
    """Graph resolution finds a package even when req_type differs.

    If a package appears as a build-system dependency in the previous graph
    but is now encountered as an install dependency (or vice-versa), the
    strict req_type filter causes the lookup to fail, falling back to PyPI
    and potentially picking up a newer version.
    """
    # Previous graph: foo==1.0 --[build-system]--> bar==2.0
    prev_graph = DependencyGraph()
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo"),
        req_version=Version("1.0"),
    )
    prev_graph.add_dependency(
        parent_name=canonicalize_name("foo"),
        parent_version=Version("1.0"),
        req_type=RequirementType.BUILD_SYSTEM,
        req=Requirement("bar>=1.0"),
        req_version=Version("2.0"),
    )

    resolver = RequirementResolver(tmp_context, prev_graph)

    # Now resolve bar>=1.5 as an INSTALL dep of foo (different req_type).
    # bar==2.0 satisfies >=1.5 and exists in the graph under the same parent
    # but with a different req_type.
    result = resolver._resolve_from_graph(
        req=Requirement("bar>=1.5"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    )
    assert result is not None, (
        "Expected bar==2.0 from prev_graph but got None (would fall back to PyPI)"
    )
    assert result == [("", Version("2.0"))]


def test_resolve_from_graph_parent_specific_preferred_over_name_fallback(
    tmp_context: WorkContext,
) -> None:
    """Parent-specific lookup is preferred over the name-based fallback.

    When the previous graph contains a package under the exact parent and
    req_type being requested, the parent-specific result must be returned
    even though the name-based fallback would also find candidates.
    """
    # Previous graph:
    #   ROOT -> foo==1.0 --[install]--> bar==2.0
    #   ROOT -> baz==1.0 --[install]--> bar==3.0
    prev_graph = DependencyGraph()
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo"),
        req_version=Version("1.0"),
    )
    prev_graph.add_dependency(
        parent_name=canonicalize_name("foo"),
        parent_version=Version("1.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("bar>=1.0"),
        req_version=Version("2.0"),
    )
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("baz"),
        req_version=Version("1.0"),
    )
    prev_graph.add_dependency(
        parent_name=canonicalize_name("baz"),
        parent_version=Version("1.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("bar>=1.0"),
        req_version=Version("3.0"),
    )

    resolver = RequirementResolver(tmp_context, prev_graph)

    # Resolve bar>=1.0 as install dep of foo.  The parent-specific lookup
    # should return bar==2.0 (from foo), NOT bar==3.0 (from baz via fallback).
    result = resolver._resolve_from_graph(
        req=Requirement("bar>=1.0"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    )
    assert result is not None
    assert result == [("", Version("2.0"))]


def test_resolve_from_graph_name_fallback_returns_none_for_missing_package(
    tmp_context: WorkContext,
) -> None:
    """Name-based fallback returns None when the package is not in the graph.

    When the previous graph is populated but does not contain the requested
    package under any parent or req_type, both the parent-specific lookup
    and the name-based fallback should return None so that resolution
    proceeds to PyPI.
    """
    # Previous graph has packages, but NOT "missing-pkg".
    prev_graph = DependencyGraph()
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo"),
        req_version=Version("1.0"),
    )
    prev_graph.add_dependency(
        parent_name=canonicalize_name("foo"),
        parent_version=Version("1.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("bar>=1.0"),
        req_version=Version("2.0"),
    )

    resolver = RequirementResolver(tmp_context, prev_graph)

    result = resolver._resolve_from_graph(
        req=Requirement("missing-pkg>=1.0"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    )
    assert result is None


def test_resolve_rejects_git_urls_for_source(tmp_context: WorkContext) -> None:
    """RequirementResolver.resolve() rejects git URLs when pre_built=False."""
    resolver = RequirementResolver(tmp_context)

    with pytest.raises(
        ValueError, match="Git URL requirements must be handled by Bootstrapper"
    ):
        resolver.resolve(
            req=Requirement("package @ git+https://github.com/example/repo.git"),
            req_type=RequirementType.TOP_LEVEL,
            pre_built=False,
            parent_req=None,
        )


@patch("fromager.requirement_resolver.wheels.resolve_prebuilt_wheel_all")
@patch("fromager.requirement_resolver.wheels.get_wheel_server_urls")
def test_resolve_allows_git_urls_for_prebuilt(
    mock_get_servers: MagicMock,
    mock_resolve_wheel: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """RequirementResolver.resolve() allows git URLs when pre_built=True (test mode fallback)."""
    resolver = RequirementResolver(tmp_context)
    req = Requirement("mypkg @ git+https://github.com/example/repo.git")

    # Mock wheel resolution to return expected result (as list)
    mock_get_servers.return_value = ["https://pypi.org/simple"]
    mock_resolve_wheel.return_value = [
        ("https://files.pythonhosted.org/mypkg-1.0-py3-none-any.whl", Version("1.0"))
    ]

    # Should NOT raise - git URLs are allowed when explicitly requesting prebuilt
    url, version = resolver.resolve(
        req=req,
        req_type=RequirementType.INSTALL,
        pre_built=True,
        parent_req=None,
    )

    # Verify it routed to wheel resolution
    mock_resolve_wheel.assert_called_once()
    assert url == "https://files.pythonhosted.org/mypkg-1.0-py3-none-any.whl"
    assert version == Version("1.0")


@patch("fromager.requirement_resolver.wheels.resolve_prebuilt_wheel_all")
@patch("fromager.requirement_resolver.wheels.get_wheel_server_urls")
def test_resolve_auto_routes_to_prebuilt(
    mock_get_servers: MagicMock,
    mock_resolve_wheel: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=None) with pbi.pre_built=True routes to wheels.resolve_prebuilt_wheel_all."""
    req = Requirement("setuptools>=40")

    # Mock package build info to return pre_built=True
    mock_pbi = MagicMock()
    mock_pbi.pre_built = True

    with patch.object(tmp_context, "package_build_info", return_value=mock_pbi):
        resolver = RequirementResolver(tmp_context)

        # Mock wheel resolution to return expected result (as list)
        mock_get_servers.return_value = ["https://pypi.org/simple"]
        mock_resolve_wheel.return_value = [
            (
                "https://files.pythonhosted.org/setuptools-1.0-py3-none-any.whl",
                Version("1.0"),
            )
        ]

        # Call resolve with pre_built=None (should auto-detect)
        url, version = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=None,
        )

        # Verify it routed to wheel resolution
        mock_resolve_wheel.assert_called_once()
        assert url == "https://files.pythonhosted.org/setuptools-1.0-py3-none-any.whl"
        assert version == Version("1.0")


@patch("fromager.requirement_resolver.sources.resolve_source_all")
def test_resolve_auto_routes_to_source(
    mock_resolve_source: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=None) with pbi.pre_built=False routes to sources.resolve_source_all."""
    req = Requirement("mypackage>=1.0")

    # Mock package build info to return pre_built=False
    mock_pbi = MagicMock()
    mock_pbi.pre_built = False

    with patch.object(tmp_context, "package_build_info", return_value=mock_pbi):
        resolver = RequirementResolver(tmp_context)

        # Mock source resolution to return expected result (as list)
        mock_resolve_source.return_value = [
            ("https://files.pythonhosted.org/mypackage-2.0.tar.gz", Version("2.0"))
        ]

        # Call resolve with pre_built=None (should auto-detect)
        url, version = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=None,
        )

        # Verify it routed to source resolution
        mock_resolve_source.assert_called_once()
        assert url == "https://files.pythonhosted.org/mypackage-2.0.tar.gz"
        assert version == Version("2.0")


@patch("fromager.requirement_resolver.wheels.resolve_prebuilt_wheel_all")
@patch("fromager.requirement_resolver.wheels.get_wheel_server_urls")
@patch("fromager.requirement_resolver.sources.resolve_source_all")
def test_resolve_prebuilt_after_source_uses_separate_cache(
    mock_resolve_source: MagicMock,
    mock_get_servers: MagicMock,
    mock_resolve_wheel: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=True) after same req resolved as source uses separate cache."""
    req = Requirement("testpkg==1.5")

    # Mock package build info to return pre_built=False initially
    mock_pbi = MagicMock()
    mock_pbi.pre_built = False

    with patch.object(tmp_context, "package_build_info", return_value=mock_pbi):
        resolver = RequirementResolver(tmp_context)

        # Mock source resolution (as list)
        mock_resolve_source.return_value = [
            ("https://files.pythonhosted.org/testpkg-1.5.tar.gz", Version("1.5"))
        ]

        # First call: resolve as source (pre_built=None, auto-detects to False)
        url1, version1 = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=None,
        )

        assert url1 == "https://files.pythonhosted.org/testpkg-1.5.tar.gz"
        assert version1 == Version("1.5")
        assert mock_resolve_source.call_count == 1

        # Mock wheel resolution for second call (as list)
        mock_get_servers.return_value = ["https://pypi.org/simple"]
        mock_resolve_wheel.return_value = [
            (
                "https://files.pythonhosted.org/testpkg-1.5-py3-none-any.whl",
                Version("1.5"),
            )
        ]

        # Second call: resolve same req as prebuilt (explicit pre_built=True)
        # This should NOT return the cached source result
        url2, version2 = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=True,
        )

        # Verify it called wheel resolution (not cached)
        assert mock_resolve_wheel.call_count == 1
        assert url2 == "https://files.pythonhosted.org/testpkg-1.5-py3-none-any.whl"
        assert version2 == Version("1.5")

        # Verify source was only called once (first time, not second)
        assert mock_resolve_source.call_count == 1
