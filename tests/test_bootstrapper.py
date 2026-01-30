import json
import pathlib
from unittest.mock import Mock, patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper, requirements_file
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType, SourceType

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
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]

    # resolving new dependency that doesn't exist in graph
    assert (
        bt._resolve_from_graph(
            req_type=RequirementType.INSTALL,
            req=Requirement("xyz"),
            pre_built=False,
        )
        is None
    )

    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("7"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_upgrade(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement of pbr==8
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr==8"),
        req_version=Version("8"),
    )

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("8"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_downgrade(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement of pbr<=6
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr<=6"),
        req_version=Version("6"),
    )

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_toplevel_dep(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement for foo
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo==2"),
        req_version=Version("2"),
    )

    # simulating new bootstrap with a toplevel requirement of bar (no change)
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("bar"),
        req_version=Version("1.0.0"),
    )

    bt.why = []
    # resolving foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo==2"),
        pre_built=False,
    ) == ("", Version("2"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("2"))]
    # resolving pbr dependency of foo even if foo version changed
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("7"))

    bt.why = []
    # resolving bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("bar"),
        pre_built=False,
    ) == ("", Version("1.0.0"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))


def test_seen(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("testdist")
    version = Version("1.2")
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_seen_extras(tmp_context: WorkContext) -> None:
    req1 = Requirement("testdist")
    req2 = Requirement("testdist[extra]")
    version = Version("1.2")
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req1, version)
    bt._mark_as_seen(req1, version)
    assert bt._has_been_seen(req1, version)
    assert not bt._has_been_seen(req2, version)
    bt._mark_as_seen(req2, version)
    assert bt._has_been_seen(req1, version)
    assert bt._has_been_seen(req2, version)


def test_seen_name_canonicalization(tmp_context: WorkContext) -> None:
    req = Requirement("flit_core")
    version = Version("1.2")
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_seen_requirements_sdist(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("testdist")
    version = Version("1.2")
    assert not bt._has_been_seen(req, version, sdist_only=False)
    assert not bt._has_been_seen(req, version, sdist_only=True)
    # sdist only does not affect wheel status
    bt._mark_as_seen(req, version, sdist_only=True)
    assert bt._has_been_seen(req, version, sdist_only=True)
    assert not bt._has_been_seen(req, version, sdist_only=False)

    bt._mark_as_seen(req, version, sdist_only=False)
    assert bt._has_been_seen(req, version, sdist_only=True)
    assert bt._has_been_seen(req, version, sdist_only=False)

    req2 = Requirement("testwheel")
    assert not bt._has_been_seen(req2, version, sdist_only=False)
    assert not bt._has_been_seen(req2, version, sdist_only=True)
    # full seen affects both sdist and wheel status
    bt._mark_as_seen(req2, version, sdist_only=False)
    assert bt._has_been_seen(req2, version, sdist_only=True)
    assert bt._has_been_seen(req2, version, sdist_only=False)


def test_build_order(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        req=Requirement("buildme>1.0"),
        version=Version("6.0"),
        source_url="url",
        source_type=SourceType.SDIST,
    )
    bt._add_to_build_order(
        req=Requirement("testdist>1.0"),
        version=Version("1.2"),
        source_url="url",
        source_type=SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
        {
            "req": "testdist>1.0",
            "dist": "testdist",
            "version": "1.2",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_build_order_repeats(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("buildme[extra]>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_build_order_name_canonicalization(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("flit-core>1.0"),
        Version("3.9.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("flit_core>1.0"),
        Version("3.9.0"),
        "url",
        SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_explain(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    assert bt._explain == f"{RequirementType.TOP_LEVEL} dependency foo (1.0.0)"

    bt.why = []
    assert bt._explain == ""

    bt.why = [
        (RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0")),
        (RequirementType.BUILD_SYSTEM, Requirement("bar==4.0.0"), Version("4.0.0")),
    ]
    assert (
        bt._explain
        == f"{RequirementType.BUILD_SYSTEM} dependency bar==4.0.0 (4.0.0) for {RequirementType.TOP_LEVEL} dependency foo (1.0.0)"
    )


def test_is_build_requirement(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = []
    assert not bt._processing_build_requirement(RequirementType.TOP_LEVEL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)
    assert not bt._processing_build_requirement(RequirementType.INSTALL)

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    assert not bt._processing_build_requirement(RequirementType.INSTALL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)

    bt.why = [
        (RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0")),
        (RequirementType.BUILD_SYSTEM, Requirement("bar==4.0.0"), Version("4.0.0")),
    ]
    assert bt._processing_build_requirement(RequirementType.INSTALL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)


def test_find_cached_wheel_returns_tuple(tmp_context: WorkContext) -> None:
    """Verify _find_cached_wheel returns tuple of (Path|None, Path|None)."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    # Call method (will return None, None since no wheels exist)
    result = bt._find_cached_wheel(
        req=Requirement("test-package"),
        resolved_version=Version("1.0.0"),
    )

    # Verify return type is tuple with 2 elements
    assert isinstance(result, tuple)
    assert len(result) == 2


@patch("fromager.dependencies.get_install_dependencies_of_wheel", return_value=set())
def test_get_install_dependencies_returns_list(
    mock_get_deps: Mock, tmp_context: WorkContext
) -> None:
    """Verify _get_install_dependencies returns list."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    # Create fake wheel file and mock dependencies
    wheel_file = pathlib.Path("/fake/package-1.0.0-py3-none-any.whl")
    unpack_dir = tmp_context.work_dir

    result = bt._get_install_dependencies(
        req=Requirement("test-package"),
        resolved_version=Version("1.0.0"),
        wheel_filename=wheel_file,
        sdist_filename=None,
        sdist_root_dir=None,
        build_env=None,
        unpack_dir=unpack_dir,
    )

    # Verify return type is list
    assert isinstance(result, list)
    # Verify the mocked function was called
    mock_get_deps.assert_called_once()


def test_build_from_source_returns_dataclass(tmp_context: WorkContext) -> None:
    """Verify _build_from_source returns SourceBuildResult with correct values."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    mock_sdist_root = tmp_context.work_dir / "package-1.0.0" / "package-1.0.0"
    mock_sdist_root.parent.mkdir(parents=True, exist_ok=True)
    mock_source_file = tmp_context.work_dir / "package-1.0.0.tar.gz"
    mock_wheel = tmp_context.work_dir / "package-1.0.0-py3-none-any.whl"
    expected_unpack_dir = mock_sdist_root.parent

    with (
        patch("fromager.sources.download_source", return_value=mock_source_file),
        patch("fromager.sources.prepare_source", return_value=mock_sdist_root),
        patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        patch.object(bt, "_prepare_build_dependencies"),
        patch.object(bt, "_build_wheel", return_value=(mock_wheel, None)),
    ):
        result = bt._build_from_source(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
            source_url="https://pypi.org/simple/test-package",
            req_type=requirements_file.RequirementType.TOP_LEVEL,
            build_sdist_only=False,
            cached_wheel_filename=None,
            unpacked_cached_wheel=None,
        )

        # Verify return type is SourceBuildResult
        assert isinstance(result, bootstrapper.SourceBuildResult)

        # Verify all expected fields have correct values
        assert result.wheel_filename == mock_wheel
        assert result.sdist_filename is None
        assert result.unpack_dir == expected_unpack_dir
        assert result.sdist_root_dir == mock_sdist_root
        assert result.build_env is not None
        assert result.source_type == SourceType.SDIST


# =============================================================================
# Tests for all_versions mode (Issue #878)
#
# These tests verify the "all-versions" mode functionality which allows
# building multiple versions of packages instead of just the newest.
# =============================================================================


def test_bootstrapper_all_versions_flag(tmp_context: WorkContext) -> None:
    """Verify Bootstrapper accepts all_versions parameter.

    The all_versions flag should be stored and accessible on the
    Bootstrapper instance.
    """
    # Default is False
    bt1 = bootstrapper.Bootstrapper(tmp_context)
    assert bt1.all_versions is False

    # Can be explicitly set to True
    bt2 = bootstrapper.Bootstrapper(tmp_context, all_versions=True)
    assert bt2.all_versions is True


def test_version_exists_in_cache_no_cache_url(tmp_context: WorkContext) -> None:
    """Verify _version_exists_in_cache returns False when no cache URL is set.

    When there's no cache wheel server URL configured, the function should
    return False immediately without attempting any network operations.
    """
    bt = bootstrapper.Bootstrapper(tmp_context, cache_wheel_server_url=None)
    # Override to ensure no cache URL
    bt.cache_wheel_server_url = ""

    result = bt._version_exists_in_cache(
        req=Requirement("test-package"),
        version=Version("1.0.0"),
    )

    assert result is False


def test_version_exists_in_cache_not_found(tmp_context: WorkContext) -> None:
    """Verify _version_exists_in_cache returns False when version not in cache.

    When the cache server doesn't have the requested version, the function
    should catch the resolution exception and return False.
    """
    bt = bootstrapper.Bootstrapper(
        tmp_context, cache_wheel_server_url="http://cache.example.com/simple"
    )

    # Mock the resolver to raise an exception (version not found)
    with patch("fromager.resolver.resolve", side_effect=Exception("Not found")):
        result = bt._version_exists_in_cache(
            req=Requirement("test-package"),
            version=Version("1.0.0"),
        )

    assert result is False


def test_version_exists_in_cache_found(tmp_context: WorkContext) -> None:
    """Verify _version_exists_in_cache returns True when version is in cache.

    When the cache server has the requested version with a matching build tag,
    the function should return True.
    """
    from fromager import wheels

    bt = bootstrapper.Bootstrapper(
        tmp_context, cache_wheel_server_url="http://cache.example.com/simple"
    )

    # Mock the resolver to return a successful result
    mock_url = "http://cache.example.com/simple/test-package/test_package-1.0.0-py3-none-any.whl"
    with (
        patch("fromager.resolver.resolve", return_value=(mock_url, Version("1.0.0"))),
        patch.object(
            wheels,
            "extract_info_from_wheel_file",
            return_value=("test-package", Version("1.0.0"), None, None),
        ),
    ):
        result = bt._version_exists_in_cache(
            req=Requirement("test-package"),
            version=Version("1.0.0"),
        )

    assert result is True


def test_resolve_and_add_top_level_all_versions_returns_list(
    tmp_context: WorkContext,
) -> None:
    """Verify resolve_and_add_top_level_all_versions returns a list of versions.

    This method should return a list of (url, version) tuples for all matching
    versions of the requirement.
    """
    from fromager import resolver
    from fromager.candidate import Candidate

    bt = bootstrapper.Bootstrapper(tmp_context, all_versions=True)

    # Create mock candidates
    mock_candidates = [
        Candidate(
            name="test-package",
            version=Version("2.0.0"),
            url="http://pypi.org/simple/test-package/test-package-2.0.0.tar.gz",
            is_sdist=True,
        ),
        Candidate(
            name="test-package",
            version=Version("1.5.0"),
            url="http://pypi.org/simple/test-package/test-package-1.5.0.tar.gz",
            is_sdist=True,
        ),
        Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="http://pypi.org/simple/test-package/test-package-1.0.0.tar.gz",
            is_sdist=True,
        ),
    ]

    with (
        patch.object(resolver, "resolve_all_versions", return_value=mock_candidates),
        patch.object(bt, "_version_exists_in_cache", return_value=False),
    ):
        results = bt.resolve_and_add_top_level_all_versions(
            Requirement("test-package>=1.0")
        )

    # Should return all 3 versions
    assert len(results) == 3
    versions = [v for _, v in results]
    assert Version("2.0.0") in versions
    assert Version("1.5.0") in versions
    assert Version("1.0.0") in versions


def test_resolve_and_add_top_level_all_versions_filters_cached(
    tmp_context: WorkContext,
) -> None:
    """Verify resolve_and_add_top_level_all_versions filters out cached versions.

    Versions that already exist in the cache server should be excluded from
    the returned list to avoid redundant builds.
    """
    from fromager import resolver
    from fromager.candidate import Candidate

    bt = bootstrapper.Bootstrapper(
        tmp_context,
        all_versions=True,
        cache_wheel_server_url="http://cache.example.com/simple",
    )

    # Create mock candidates
    mock_candidates = [
        Candidate(
            name="test-package",
            version=Version("2.0.0"),
            url="http://pypi.org/simple/test-package/test-package-2.0.0.tar.gz",
            is_sdist=True,
        ),
        Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="http://pypi.org/simple/test-package/test-package-1.0.0.tar.gz",
            is_sdist=True,
        ),
    ]

    def mock_cache_check(req: Requirement, version: Version) -> bool:
        # Version 1.0.0 is already in cache, 2.0.0 is not
        return version == Version("1.0.0")

    with (
        patch.object(resolver, "resolve_all_versions", return_value=mock_candidates),
        patch.object(bt, "_version_exists_in_cache", side_effect=mock_cache_check),
    ):
        results = bt.resolve_and_add_top_level_all_versions(
            Requirement("test-package>=1.0")
        )

    # Should only return version 2.0.0 (1.0.0 is cached)
    assert len(results) == 1
    _, version = results[0]
    assert version == Version("2.0.0")


def test_bootstrap_with_resolved_version(tmp_context: WorkContext) -> None:
    """Verify bootstrap() accepts optional resolved_version parameter.

    In all-versions mode, the version is already known from pre-resolution,
    so bootstrap() should use that version directly instead of re-resolving.
    """
    bt = bootstrapper.Bootstrapper(tmp_context, all_versions=True)

    # Mark a version as seen so bootstrap exits early (avoiding full build)
    version = Version("1.5.0")
    bt._mark_as_seen(Requirement("test-package"), version, sdist_only=False)

    # Mock resolve_version to track if it's called with the pinned requirement
    resolve_calls: list[Requirement] = []

    def mock_resolve(
        req: Requirement, req_type: RequirementType
    ) -> tuple[str, Version]:
        resolve_calls.append(req)
        return ("http://example.com/url", version)

    with patch.object(bt, "resolve_version", side_effect=mock_resolve):
        # Call bootstrap with a pre-resolved version
        bt.bootstrap(
            Requirement("test-package>=1.0"),
            RequirementType.TOP_LEVEL,
            resolved_version=version,
        )

    # Verify resolve_version was called with a pinned requirement
    assert len(resolve_calls) == 1
    assert "==1.5.0" in str(resolve_calls[0])


def test_bootstrap_all_dependency_versions(tmp_context: WorkContext) -> None:
    """Verify _bootstrap_all_dependency_versions resolves all versions of dependencies.

    In all-versions mode, the bootstrapper should resolve and build ALL matching
    versions of each install dependency, not just the newest version.
    """
    from fromager import resolver
    from fromager.candidate import Candidate

    bt = bootstrapper.Bootstrapper(tmp_context, all_versions=True)

    # Set up the why stack to simulate being inside a package bootstrap
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("parent-pkg"), Version("1.0.0"))]

    # Add the parent node to the dependency graph (required before adding children)
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("parent-pkg"),
        req_version=Version("1.0.0"),
    )

    # Create mock candidates for the dependency
    mock_candidates = [
        Candidate(
            name="dep-package",
            version=Version("2.0.0"),
            url="http://pypi.org/simple/dep-package/dep-package-2.0.0.tar.gz",
            is_sdist=True,
        ),
        Candidate(
            name="dep-package",
            version=Version("1.5.0"),
            url="http://pypi.org/simple/dep-package/dep-package-1.5.0.tar.gz",
            is_sdist=True,
        ),
    ]

    # Track which versions get bootstrapped
    bootstrapped_versions: list[Version] = []

    def mock_bootstrap(
        req: Requirement,
        req_type: RequirementType,
        resolved_version: Version | None = None,
    ) -> None:
        if resolved_version:
            bootstrapped_versions.append(resolved_version)

    with (
        patch.object(resolver, "resolve_all_versions", return_value=mock_candidates),
        patch.object(bt, "_version_exists_in_cache", return_value=False),
        patch.object(bt, "bootstrap", side_effect=mock_bootstrap),
    ):
        install_deps = [Requirement("dep-package>=1.0")]
        bt._bootstrap_all_dependency_versions(install_deps)

    # Both versions should be bootstrapped
    assert len(bootstrapped_versions) == 2
    assert Version("2.0.0") in bootstrapped_versions
    assert Version("1.5.0") in bootstrapped_versions


def test_bootstrap_all_dependency_versions_filters_cached(
    tmp_context: WorkContext,
) -> None:
    """Verify _bootstrap_all_dependency_versions filters out cached versions.

    Versions of dependencies that already exist in the cache server should
    be skipped to avoid redundant builds.
    """
    from fromager import resolver
    from fromager.candidate import Candidate

    bt = bootstrapper.Bootstrapper(
        tmp_context,
        all_versions=True,
        cache_wheel_server_url="http://cache.example.com/simple",
    )

    # Set up the why stack
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("parent-pkg"), Version("1.0.0"))]

    # Add the parent node to the dependency graph (required before adding children)
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("parent-pkg"),
        req_version=Version("1.0.0"),
    )

    # Create mock candidates
    mock_candidates = [
        Candidate(
            name="dep-package",
            version=Version("2.0.0"),
            url="http://pypi.org/simple/dep-package/dep-package-2.0.0.tar.gz",
            is_sdist=True,
        ),
        Candidate(
            name="dep-package",
            version=Version("1.0.0"),
            url="http://pypi.org/simple/dep-package/dep-package-1.0.0.tar.gz",
            is_sdist=True,
        ),
    ]

    def mock_cache_check(req: Requirement, version: Version) -> bool:
        # Version 1.0.0 is cached, 2.0.0 is not
        return version == Version("1.0.0")

    bootstrapped_versions: list[Version] = []

    def mock_bootstrap(
        req: Requirement,
        req_type: RequirementType,
        resolved_version: Version | None = None,
    ) -> None:
        if resolved_version:
            bootstrapped_versions.append(resolved_version)

    with (
        patch.object(resolver, "resolve_all_versions", return_value=mock_candidates),
        patch.object(bt, "_version_exists_in_cache", side_effect=mock_cache_check),
        patch.object(bt, "bootstrap", side_effect=mock_bootstrap),
    ):
        install_deps = [Requirement("dep-package>=1.0")]
        bt._bootstrap_all_dependency_versions(install_deps)

    # Only version 2.0.0 should be bootstrapped (1.0.0 is cached)
    assert len(bootstrapped_versions) == 1
    assert bootstrapped_versions[0] == Version("2.0.0")
