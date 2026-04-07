"""Tests for multiple versions feature in bootstrap_requirement_resolver."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager.bootstrap_requirement_resolver import BootstrapRequirementResolver
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType


@pytest.fixture
def tmp_context(tmp_path: Path) -> WorkContext:
    """Create a minimal WorkContext for testing."""
    ctx = MagicMock(spec=WorkContext)
    ctx.work_dir = tmp_path
    ctx.constraints = MagicMock()
    ctx.constraints.get_constraint.return_value = None
    ctx.settings = MagicMock()
    ctx.settings.list_pre_built.return_value = set()
    ctx.package_build_info = MagicMock()
    pbi = MagicMock()
    pbi.pre_built = False
    pbi.resolver_include_sdists = True
    pbi.resolver_include_wheels = False
    pbi.resolver_ignore_platform = False
    pbi.resolver_sdist_server_url.return_value = "https://pypi.org/simple/"
    ctx.package_build_info.return_value = pbi
    return ctx


def test_resolve_return_all_versions_true(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=True returns all matching versions."""
    resolver = BootstrapRequirementResolver(tmp_context)

    # Mock the _resolve method to return multiple versions
    with patch.object(
        resolver,
        "_resolve",
        return_value=[
            ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
            ("https://pypi.org/testpkg-1.5.tar.gz", Version("1.5")),
            ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
        ],
    ):
        req = Requirement("testpkg>=1.0")
        results = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )

        # Should return all 3 versions
        assert len(results) == 3
        assert results[0] == ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0"))
        assert results[1] == ("https://pypi.org/testpkg-1.5.tar.gz", Version("1.5"))
        assert results[2] == ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0"))


def test_resolve_return_all_versions_false_default(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=False (default) returns list with only highest version."""
    resolver = BootstrapRequirementResolver(tmp_context)

    # Mock the _resolve method to return multiple versions
    with patch.object(
        resolver,
        "_resolve",
        return_value=[
            ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
            ("https://pypi.org/testpkg-1.5.tar.gz", Version("1.5")),
            ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
        ],
    ):
        req = Requirement("testpkg>=1.0")

        # Call without return_all_versions (default False)
        results = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
        )

        # Should return list with only the highest version
        assert len(results) == 1
        assert results[0] == ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0"))


def test_resolve_return_all_versions_uses_cache(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=True uses cache correctly."""
    resolver = BootstrapRequirementResolver(tmp_context)

    # First call - will populate cache
    with patch.object(
        resolver,
        "_resolve",
        return_value=[
            ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
            ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
        ],
    ) as mock_resolve:
        req = Requirement("testpkg>=1.0")

        # First call
        results1 = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )
        assert len(results1) == 2
        assert mock_resolve.call_count == 1

        # Second call - should use cache
        results2 = resolver.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )

        # Should not call _resolve again
        assert mock_resolve.call_count == 1
        # Should return same results
        assert results2 == results1


def test_resolve_return_all_versions_with_previous_graph(
    tmp_context: WorkContext,
) -> None:
    """resolve() with return_all_versions=True works with previous graph."""
    # Create graph with multiple versions of the same package
    prev_graph = DependencyGraph()
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("testpkg==2.0"),
        req_version=Version("2.0"),
    )
    prev_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("testpkg==1.0"),
        req_version=Version("1.0"),
    )

    # Mock dependency_graph in context
    tmp_context.dependency_graph = prev_graph

    resolver = BootstrapRequirementResolver(tmp_context, prev_graph)

    # Request with version spec that matches both
    req = Requirement("testpkg>=1.0")
    results = resolver.resolve(
        req=req,
        req_type=RequirementType.TOP_LEVEL,
        parent_req=None,
        return_all_versions=True,
    )

    # Should return both versions from graph
    assert len(results) == 2
    # Verify versions (should be sorted highest first)
    versions = [v for _, v in results]
    assert Version("2.0") in versions
    assert Version("1.0") in versions
