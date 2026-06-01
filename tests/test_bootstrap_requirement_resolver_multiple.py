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
    ctx.max_release_age = None
    return ctx


_MOCK_VERSIONS = [
    ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
    ("https://pypi.org/testpkg-1.5.tar.gz", Version("1.5")),
    ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
]


def test_resolve_return_all_versions_true(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=True returns all matching versions."""
    brr = BootstrapRequirementResolver(tmp_context)

    with (
        patch.object(brr, "_resolve_from_graph", return_value=None),
        patch(
            "fromager.bootstrap_requirement_resolver.sources.get_source_provider",
        ),
        patch(
            "fromager.bootstrap_requirement_resolver.resolver"
            ".find_all_matching_from_provider",
            return_value=list(_MOCK_VERSIONS),
        ),
    ):
        req = Requirement("testpkg>=1.0")
        results = brr.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )

        assert len(results) == 3
        assert results[0] == _MOCK_VERSIONS[0]
        assert results[1] == _MOCK_VERSIONS[1]
        assert results[2] == _MOCK_VERSIONS[2]


def test_resolve_return_all_versions_false_default(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=False (default) returns list with only highest version."""
    brr = BootstrapRequirementResolver(tmp_context)

    with (
        patch.object(brr, "_resolve_from_graph", return_value=None),
        patch(
            "fromager.bootstrap_requirement_resolver.sources.get_source_provider",
        ),
        patch(
            "fromager.bootstrap_requirement_resolver.resolver"
            ".find_all_matching_from_provider",
            return_value=list(_MOCK_VERSIONS),
        ),
    ):
        req = Requirement("testpkg>=1.0")
        results = brr.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
        )

        assert len(results) == 1
        assert results[0] == _MOCK_VERSIONS[0]


def test_resolve_return_all_versions_uses_cache(tmp_context: WorkContext) -> None:
    """resolve() with return_all_versions=True uses cache correctly."""
    brr = BootstrapRequirementResolver(tmp_context)

    with (
        patch.object(brr, "_resolve_from_graph", return_value=None),
        patch(
            "fromager.bootstrap_requirement_resolver.sources.get_source_provider",
        ),
        patch(
            "fromager.bootstrap_requirement_resolver.resolver"
            ".find_all_matching_from_provider",
            return_value=[
                ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
                ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
            ],
        ) as mock_resolve,
    ):
        req = Requirement("testpkg>=1.0")

        results1 = brr.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )
        assert len(results1) == 2
        assert mock_resolve.call_count == 1

        results2 = brr.resolve(
            req=req,
            req_type=RequirementType.INSTALL,
            parent_req=None,
            return_all_versions=True,
        )

        # Should not call resolution again — cache hit
        assert mock_resolve.call_count == 1
        assert results2 == results1


def test_resolve_return_all_versions_with_previous_graph(
    tmp_context: WorkContext,
) -> None:
    """resolve() with return_all_versions=True works with previous graph."""
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

    tmp_context.dependency_graph = prev_graph

    brr = BootstrapRequirementResolver(tmp_context, prev_graph)

    req = Requirement("testpkg>=1.0")
    results = brr.resolve(
        req=req,
        req_type=RequirementType.TOP_LEVEL,
        parent_req=None,
        return_all_versions=True,
    )

    assert len(results) == 2
    versions = [v for _, v in results]
    assert Version("2.0") in versions
    assert Version("1.0") in versions
