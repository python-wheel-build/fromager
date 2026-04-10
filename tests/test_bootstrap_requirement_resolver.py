"""Tests for bootstrap_requirement_resolver module."""

from unittest.mock import MagicMock, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.bootstrap_requirement_resolver import BootstrapRequirementResolver
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
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
    """BootstrapRequirementResolver resolves from previous graph with no changes."""
    resolver = BootstrapRequirementResolver(tmp_context, old_graph)

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
    """BootstrapRequirementResolver prefers top-level requirements over history."""
    resolver = BootstrapRequirementResolver(tmp_context, old_graph)

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
    """BootstrapRequirementResolver handles version downgrades from top-level requirements."""
    resolver = BootstrapRequirementResolver(tmp_context, old_graph)

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
    """BootstrapRequirementResolver resolves top-level dependencies correctly."""
    resolver = BootstrapRequirementResolver(tmp_context, old_graph)

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
    """BootstrapRequirementResolver returns None when no previous graph is available."""
    resolver = BootstrapRequirementResolver(tmp_context, prev_graph=None)

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

    resolver = BootstrapRequirementResolver(tmp_context, prev_graph)

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

    resolver = BootstrapRequirementResolver(tmp_context, prev_graph)

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

    resolver = BootstrapRequirementResolver(tmp_context, prev_graph)

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

    resolver = BootstrapRequirementResolver(tmp_context, prev_graph)

    result = resolver._resolve_from_graph(
        req=Requirement("missing-pkg>=1.0"),
        req_type=RequirementType.INSTALL,
        pre_built=False,
        parent_req=Requirement("foo"),
    )
    assert result is None


def test_resolve_rejects_git_urls_for_source(tmp_context: WorkContext) -> None:
    """BootstrapRequirementResolver.resolve() rejects git URLs when pre_built=False."""
    resolver = BootstrapRequirementResolver(tmp_context)

    with pytest.raises(
        ValueError, match="Git URL requirements must be handled by Bootstrapper"
    ):
        resolver.resolve(
            req=Requirement("package @ git+https://github.com/example/repo.git"),
            req_type=RequirementType.TOP_LEVEL,
            pre_built=False,
            parent_req=None,
        )


@patch("fromager.resolver.find_all_matching_from_provider")
def test_resolve_allows_git_urls_for_prebuilt(
    mock_resolve: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """BootstrapRequirementResolver.resolve() allows git URLs when pre_built=True (test mode fallback)."""
    resolver = BootstrapRequirementResolver(tmp_context)
    req = Requirement("mypkg @ git+https://github.com/example/repo.git")

    # Mock resolution to return expected result (as list)
    mock_resolve.return_value = [
        ("https://files.pythonhosted.org/mypkg-1.0-py3-none-any.whl", Version("1.0"))
    ]

    # Should NOT raise - git URLs are allowed when explicitly requesting prebuilt
    results = resolver.resolve(
        req=req,
        req_type=RequirementType.INSTALL,
        pre_built=True,
        parent_req=None,
    )

    # Verify resolution was called
    mock_resolve.assert_called_once()
    assert len(results) == 1
    url, version = results[0]
    assert url == "https://files.pythonhosted.org/mypkg-1.0-py3-none-any.whl"
    assert version == Version("1.0")


@patch("fromager.resolver.find_all_matching_from_provider")
def test_resolve_auto_routes_to_prebuilt(
    mock_resolve: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=None) with pbi.pre_built=True routes to wheel resolution."""
    req = Requirement("setuptools>=40")

    # Mock package build info to return pre_built=True
    mock_pbi = MagicMock()
    mock_pbi.pre_built = True
    mock_pbi.wheel_server_url = None

    with patch.object(tmp_context, "package_build_info", return_value=mock_pbi):
        resolver = BootstrapRequirementResolver(tmp_context)

        # Mock resolution to return expected result (as list)
        mock_resolve.return_value = [
            (
                "https://files.pythonhosted.org/setuptools-1.0-py3-none-any.whl",
                Version("1.0"),
            )
        ]

        # Call resolve with pre_built=None (should auto-detect)
        results = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=None,
        )

        # Verify resolution was called
        mock_resolve.assert_called_once()
        assert len(results) == 1
        url, version = results[0]
        assert url == "https://files.pythonhosted.org/setuptools-1.0-py3-none-any.whl"
        assert version == Version("1.0")


@patch("fromager.resolver.find_all_matching_from_provider")
def test_resolve_auto_routes_to_source(
    mock_resolve: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=None) with pbi.pre_built=False routes to source resolution."""
    req = Requirement("mypackage>=1.0")

    # Mock package build info to return pre_built=False
    mock_pbi = MagicMock()
    mock_pbi.pre_built = False
    mock_pbi.resolver_include_sdists = True
    mock_pbi.resolver_include_wheels = True
    mock_pbi.resolver_ignore_platform = True
    mock_pbi.resolver_sdist_server_url = MagicMock(
        return_value="https://pypi.org/simple"
    )

    with patch.object(tmp_context, "package_build_info", return_value=mock_pbi):
        resolver = BootstrapRequirementResolver(tmp_context)

        # Mock source resolution to return expected result (as list)
        mock_resolve.return_value = [
            ("https://files.pythonhosted.org/mypackage-2.0.tar.gz", Version("2.0"))
        ]

        # Call resolve with pre_built=None (should auto-detect)
        results = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            pre_built=None,
        )

        # Verify resolution was called
        mock_resolve.assert_called_once()
        assert len(results) == 1
        url, version = results[0]
        assert url == "https://files.pythonhosted.org/mypackage-2.0.tar.gz"
        assert version == Version("2.0")


@patch("fromager.resolver.find_all_matching_from_provider")
def test_resolve_prebuilt_after_source_uses_separate_cache(
    mock_resolve: MagicMock,
    tmp_context: WorkContext,
) -> None:
    """resolve(pre_built=True) after same req resolved as source uses separate cache."""
    req = Requirement("testpkg==1.5")

    # Set up side_effect to return different results for each call
    mock_resolve.side_effect = [
        # First call: source resolution
        [("https://files.pythonhosted.org/testpkg-1.5.tar.gz", Version("1.5"))],
        # Second call: wheel resolution
        [
            (
                "https://files.pythonhosted.org/testpkg-1.5-py3-none-any.whl",
                Version("1.5"),
            )
        ],
    ]

    resolver = BootstrapRequirementResolver(tmp_context)

    # First call: resolve as source (explicit pre_built=False)
    results1 = resolver.resolve(
        req=req,
        req_type=RequirementType.INSTALL,
        parent_req=None,
        pre_built=False,
    )

    assert len(results1) == 1
    url1, version1 = results1[0]
    assert url1 == "https://files.pythonhosted.org/testpkg-1.5.tar.gz"
    assert version1 == Version("1.5")
    assert mock_resolve.call_count == 1

    # Second call: resolve same req as prebuilt (explicit pre_built=True)
    # This should NOT return the cached source result
    results2 = resolver.resolve(
        req=req,
        req_type=RequirementType.INSTALL,
        parent_req=None,
        pre_built=True,
    )

    # Verify it called resolution again (not cached) because cache keys differ
    assert mock_resolve.call_count == 2
    assert len(results2) == 1
    url2, version2 = results2[0]
    assert url2 == "https://files.pythonhosted.org/testpkg-1.5-py3-none-any.whl"
    assert version2 == Version("1.5")
