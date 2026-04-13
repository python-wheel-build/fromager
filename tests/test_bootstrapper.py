import json
import pathlib
from unittest.mock import Mock, patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper, requirements_file
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType, SourceType


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
    bt = bootstrapper.Bootstrapper(tmp_context)
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
    bt = bootstrapper.Bootstrapper(tmp_context)
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


def test_multiple_versions_continues_on_error(tmp_context: WorkContext) -> None:
    """Test that multiple versions mode continues when one version fails."""
    # Enable multiple versions mode
    bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)

    # Mock the resolver to return 3 versions
    with patch.object(
        bt._resolver,
        "resolve",
        return_value=[
            ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
            ("https://pypi.org/testpkg-1.5.tar.gz", Version("1.5")),
            ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
        ],
    ):
        # Mock _bootstrap_impl to fail for version 1.5 only
        call_count = {"count": 0}

        def mock_bootstrap_impl(
            req: Requirement,
            req_type: RequirementType,
            source_url: str,
            resolved_version: Version,
            build_sdist_only: bool,
        ) -> None:
            call_count["count"] += 1
            if str(resolved_version) == "1.5":
                raise ValueError("Simulated failure for version 1.5")
            # For other versions, just mark as seen to avoid actual build
            bt._mark_as_seen(req, resolved_version, build_sdist_only)

        with patch.object(bt, "_bootstrap_impl", side_effect=mock_bootstrap_impl):
            # Mock _has_been_seen to return False so we attempt bootstrap
            with patch.object(bt, "_has_been_seen", return_value=False):
                # Capture log output
                with patch("fromager.bootstrapper.logger") as mock_logger:
                    req = Requirement("testpkg>=1.0")

                    # Call bootstrap with INSTALL type (not TOP_LEVEL, since TOP_LEVEL
                    # nodes are added in resolve_and_add_top_level())
                    bt.bootstrap(
                        req=req,
                        req_type=RequirementType.INSTALL,
                    )

                    # Verify _bootstrap_impl was called 3 times (all versions attempted)
                    assert call_count["count"] == 3

                    # Verify that version 1.5 is in failed_versions
                    assert len(bt._failed_versions) == 1
                    pkg_name, version_str, exc = bt._failed_versions[0]
                    assert pkg_name == canonicalize_name("testpkg")
                    assert version_str == "1.5"
                    assert isinstance(exc, ValueError)
                    assert str(exc) == "Simulated failure for version 1.5"

                    # Verify that a warning was logged for the failed version
                    warning_calls = [
                        call
                        for call in mock_logger.warning.call_args_list
                        if "failed to bootstrap" in str(call)
                    ]
                    assert len(warning_calls) >= 1

                    # Verify that failed version 1.5 is NOT in the dependency graph
                    # (should have been removed)
                    failed_key = f"{canonicalize_name('testpkg')}==1.5"
                    assert failed_key not in tmp_context.dependency_graph.nodes

                    # Verify that successful versions ARE in the dependency graph
                    success_key_20 = f"{canonicalize_name('testpkg')}==2.0"
                    success_key_10 = f"{canonicalize_name('testpkg')}==1.0"
                    assert success_key_20 in tmp_context.dependency_graph.nodes
                    assert success_key_10 in tmp_context.dependency_graph.nodes


@patch("fromager.resolver.find_all_matching_from_provider")
@patch("fromager.resolver.PyPIProvider")
def test_download_wheel_from_cache_bypasses_hooks(
    mock_pypi_provider: Mock,
    mock_find_all: Mock,
    tmp_context: WorkContext,
) -> None:
    """Verify _download_wheel_from_cache uses PyPIProvider directly, not hooks."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt.cache_wheel_server_url = "https://cache.example.com/simple/"

    mock_provider = Mock()
    mock_pypi_provider.return_value = mock_provider
    # Raise so the except clause returns (None, None) before hitting
    # network calls later in the function.
    mock_find_all.side_effect = RuntimeError("no match")

    with patch("fromager.overrides.find_and_invoke") as mock_override:
        result = bt._download_wheel_from_cache(
            req=Requirement("test-pkg"),
            resolved_version=Version("1.0.0"),
        )

    assert result == (None, None)

    # Hook system must NOT be called for cache lookups
    mock_override.assert_not_called()

    # PyPIProvider must be instantiated directly
    mock_pypi_provider.assert_called_once_with(
        sdist_server_url="https://cache.example.com/simple/",
        include_sdists=False,
        include_wheels=True,
        constraints=tmp_context.constraints,
    )
    mock_find_all.assert_called_once_with(mock_provider, Requirement("test-pkg==1.0.0"))
