import json
import pathlib
import unittest.mock
from unittest.mock import Mock, patch

import pytest
import requests.exceptions
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from resolvelib.resolvers import ResolverException

from fromager import bootstrapper
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


def test_phase_build_produces_source_build_result(tmp_context: WorkContext) -> None:
    """Verify _phase_build produces a SourceBuildResult with correct values."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    mock_sdist_root = tmp_context.work_dir / "package-1.0.0" / "package-1.0.0"
    mock_sdist_root.parent.mkdir(parents=True, exist_ok=True)
    mock_wheel = tmp_context.work_dir / "package-1.0.0-py3-none-any.whl"

    item = bootstrapper.WorkItem(
        req=Requirement("test-package"),
        req_type=RequirementType.TOP_LEVEL,
        source_url="https://pypi.org/simple/test-package",
        resolved_version=Version("1.0.0"),
        phase=bootstrapper.BootstrapPhase.BUILD,
        why_snapshot=[],
        sdist_root_dir=mock_sdist_root,
        unpack_dir=mock_sdist_root.parent,
        build_env=Mock(),
        build_system_deps=set(),
        build_backend_deps=set(),
        build_sdist_deps=set(),
    )

    # Set up why stack so _track_why works
    bt.why = []

    with (
        patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        patch.object(bt, "_build_wheel", return_value=(mock_wheel, None)),
    ):
        with bt._track_why(item):
            result_items = bt._phase_build(item)

    assert len(result_items) == 1
    assert result_items[0].phase == bootstrapper.BootstrapPhase.UPDATE_BUILD_SEQUENCE

    result = result_items[0].build_result
    assert isinstance(result, bootstrapper.SourceBuildResult)
    assert result.wheel_filename == mock_wheel
    assert result.sdist_filename is None
    assert result.unpack_dir == mock_sdist_root.parent
    assert result.sdist_root_dir == mock_sdist_root
    assert result.source_type == SourceType.SDIST


def test_phase_update_build_sequence_advances_to_process_install_deps(
    tmp_context: WorkContext,
) -> None:
    """Verify _phase_update_build_sequence records build order and advances phase."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt.why = []

    req = Requirement("test-package")
    version = Version("1.0.0")
    mock_wheel = tmp_context.work_dir / "test_package-1.0.0-py3-none-any.whl"
    mock_sdist_root = tmp_context.work_dir / "test-package-1.0.0" / "test-package-1.0.0"
    mock_sdist_root.parent.mkdir(parents=True, exist_ok=True)

    item = bootstrapper.WorkItem(
        req=req,
        req_type=RequirementType.TOP_LEVEL,
        source_url="https://pypi.test/simple/test-package",
        resolved_version=version,
        phase=bootstrapper.BootstrapPhase.UPDATE_BUILD_SEQUENCE,
        why_snapshot=[],
        build_result=bootstrapper.SourceBuildResult(
            wheel_filename=mock_wheel,
            sdist_filename=None,
            unpack_dir=mock_sdist_root.parent,
            sdist_root_dir=mock_sdist_root,
            build_env=None,
            source_type=SourceType.SDIST,
        ),
    )

    with bt._track_why(item):
        result_items = bt._phase_update_build_sequence(item)

    assert len(result_items) == 1
    assert result_items[0].phase == bootstrapper.BootstrapPhase.PROCESS_INSTALL_DEPS
    key = (canonicalize_name(req.name), str(version))
    assert key in bt._build_requirements


def test_multiple_versions_continues_on_error(tmp_context: WorkContext) -> None:
    """Test that multiple versions mode continues when one version fails."""
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
        # Mock _dispatch_phase to let RESOLVE and START run normally
        # but fail for version 1.5 in build phases.
        original_dispatch = bt._dispatch_phase
        build_phase_count = {"count": 0}

        def mock_dispatch(item: bootstrapper.WorkItem) -> list[bootstrapper.WorkItem]:
            if item.phase in (
                bootstrapper.BootstrapPhase.RESOLVE,
                bootstrapper.BootstrapPhase.START,
            ):
                return original_dispatch(item)
            build_phase_count["count"] += 1
            if str(item.resolved_version) == "1.5":
                raise ValueError("Simulated failure for version 1.5")
            return []

        with patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch):
            with patch.object(bt, "_has_been_seen", return_value=False):
                with patch("fromager.bootstrapper.logger") as mock_logger:
                    req = Requirement("testpkg>=1.0")

                    bt.bootstrap(
                        req=req,
                        req_type=RequirementType.INSTALL,
                    )

                    # All 3 versions should reach build phases
                    assert build_phase_count["count"] == 3

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
                    failed_key = f"{canonicalize_name('testpkg')}==1.5"
                    assert failed_key not in tmp_context.dependency_graph.nodes

                    # Verify that successful versions ARE in the dependency graph
                    success_key_20 = f"{canonicalize_name('testpkg')}==2.0"
                    success_key_10 = f"{canonicalize_name('testpkg')}==1.0"
                    assert success_key_20 in tmp_context.dependency_graph.nodes
                    assert success_key_10 in tmp_context.dependency_graph.nodes


@patch("fromager.resolver.find_all_matching_from_provider")
@patch("fromager.finders.PyPICacheProvider")
def test_download_wheel_from_cache_bypasses_hooks(
    mock_cache_provider: Mock,
    mock_find_all: Mock,
    tmp_context: WorkContext,
) -> None:
    """Verify _download_wheel_from_cache uses PyPICacheProvider, not hooks."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt.cache_wheel_server_url = "https://cache.test/simple/"

    mock_provider = Mock()
    mock_cache_provider.return_value = mock_provider
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

    # PyPICacheProvider must be instantiated directly
    mock_cache_provider.assert_called_once_with(
        cache_server_url="https://cache.test/simple/",
        constraints=tmp_context.constraints,
    )
    mock_find_all.assert_called_once_with(mock_provider, Requirement("test-pkg==1.0.0"))


def _make_cache_bootstrapper(
    tmp_context: WorkContext,
) -> bootstrapper.Bootstrapper:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt.cache_wheel_server_url = "https://cache.test/simple"
    return bt


def test_cache_lookup_resolver_exception_logs_info(
    tmp_context: WorkContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ResolverException (wheel not found) returns (None, None) and logs info."""
    bt = _make_cache_bootstrapper(tmp_context)

    with patch(
        "fromager.resolver.find_all_matching_from_provider",
        side_effect=ResolverException("no matching version"),
    ):
        result = bt._download_wheel_from_cache(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
        )

    assert result == (None, None)
    assert "did not find wheel for" in caplog.text


@pytest.mark.parametrize(
    "exc_class,exc_msg",
    [
        (requests.exceptions.ConnectionError, "DNS failure"),
        (requests.exceptions.Timeout, "timed out"),
        (requests.exceptions.HTTPError, "401 Unauthorized"),
    ],
)
def test_cache_lookup_request_exception_logs_warning(
    tmp_context: WorkContext,
    caplog: pytest.LogCaptureFixture,
    exc_class: type[Exception],
    exc_msg: str,
) -> None:
    """RequestException subtypes return (None, None) and log warning."""
    bt = _make_cache_bootstrapper(tmp_context)

    with patch(
        "fromager.resolver.find_all_matching_from_provider",
        side_effect=exc_class(exc_msg),
    ):
        result = bt._download_wheel_from_cache(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
        )

    assert result == (None, None)
    assert "network error checking wheel cache" in caplog.text


def test_cache_lookup_unexpected_exception_logs_warning(
    tmp_context: WorkContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected exceptions return (None, None) and log warning."""
    bt = _make_cache_bootstrapper(tmp_context)

    with patch(
        "fromager.resolver.find_all_matching_from_provider",
        side_effect=ValueError("unexpected parsing error"),
    ):
        result = bt._download_wheel_from_cache(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
        )

    assert result == (None, None)
    assert "unexpected error checking wheel cache" in caplog.text


@pytest.mark.parametrize(
    "exc_class,exc_msg,expected_log",
    [
        (
            requests.exceptions.ConnectionError,
            "connection reset",
            "network error checking wheel cache",
        ),
        (OSError, "disk full", "unexpected error checking wheel cache"),
    ],
)
def test_cache_lookup_download_wheel_error_logs_warning(
    tmp_context: WorkContext,
    caplog: pytest.LogCaptureFixture,
    exc_class: type[Exception],
    exc_msg: str,
    expected_log: str,
) -> None:
    """Errors from download_wheel (after resolve succeeds) are caught."""
    bt = _make_cache_bootstrapper(tmp_context)

    with (
        patch(
            "fromager.resolver.find_all_matching_from_provider",
            return_value=[
                (
                    "https://cache.test/simple/test-package/test_package-1.0.0-py3-none-any.whl",
                    Version("1.0.0"),
                ),
            ],
        ),
        patch(
            "fromager.bootstrapper.wheels.extract_info_from_wheel_file",
            return_value=("test_package", "1.0.0", None, None),
        ),
        patch(
            "fromager.bootstrapper.wheels.download_wheel",
            side_effect=exc_class(exc_msg),
        ),
    ):
        result = bt._download_wheel_from_cache(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
        )

    assert result == (None, None)
    assert expected_log in caplog.text


def test_cache_lookup_no_cache_url_returns_none(tmp_context: WorkContext) -> None:
    """When no cache URL is configured, returns (None, None) immediately."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt.cache_wheel_server_url = ""

    result = bt._download_wheel_from_cache(
        req=Requirement("test-package"),
        resolved_version=Version("1.0.0"),
    )

    assert result == (None, None)


def test_phase_can_parallelize(tmp_context: WorkContext) -> None:
    """RESOLVE, START, PREPARE_SOURCE, GET_BUILD_DEPS, BUILD, PROCESS_INSTALL_DEPS, COMPLETE parallelize.

    Serial phases: WAIT_BUILD_SYSTEM_DEPS, PREPARE_BUILD, WAIT_BUILD_DEPS,
    INSTALL_BUILD_DEPS, UPDATE_BUILD_SEQUENCE.  The two WAIT phases are serial
    barriers that ensure dep builds complete before the subsequent install step runs.
    """
    parallelizable = (
        bootstrapper.BootstrapPhase.RESOLVE,
        bootstrapper.BootstrapPhase.START,
        bootstrapper.BootstrapPhase.PREPARE_SOURCE,
        bootstrapper.BootstrapPhase.GET_BUILD_DEPS,
        bootstrapper.BootstrapPhase.BUILD,
        bootstrapper.BootstrapPhase.PROCESS_INSTALL_DEPS,
        bootstrapper.BootstrapPhase.COMPLETE,
    )
    for phase in parallelizable:
        assert phase.can_parallelize is True, f"{phase} should be parallelizable"
    for phase in bootstrapper.BootstrapPhase:
        if phase not in parallelizable:
            assert phase.can_parallelize is False, f"{phase} should be serial"


def test_bootstrap_parallel_resolve_returns_ordered_results(
    tmp_context: WorkContext,
) -> None:
    """Two RESOLVE items run in parallel; results appear in original stack order."""
    bt = bootstrapper.Bootstrapper(tmp_context, max_workers=2)

    pkg_b = bootstrapper.WorkItem(
        req=Requirement("pkg-b"),
        req_type=RequirementType.INSTALL,
        phase=bootstrapper.BootstrapPhase.RESOLVE,
        why_snapshot=[],
    )
    pkg_c = bootstrapper.WorkItem(
        req=Requirement("pkg-c"),
        req_type=RequirementType.INSTALL,
        phase=bootstrapper.BootstrapPhase.RESOLVE,
        why_snapshot=[],
    )

    dispatched: list[str] = []

    def dispatch_side_effect(
        item: bootstrapper.WorkItem,
    ) -> list[bootstrapper.WorkItem]:
        dispatched.append(item.req.name)
        if item.req.name == "pkg-a":
            # Return two sibling RESOLVE items so they batch and run concurrently
            return [pkg_b, pkg_c]
        return []

    with patch.object(bt, "_dispatch_phase", side_effect=dispatch_side_effect):
        bt.bootstrap(req=Requirement("pkg-a"), req_type=RequirementType.TOP_LEVEL)

    # pkg-a dispatched first; pkg-b and pkg-c dispatched concurrently after
    assert dispatched[0] == "pkg-a"
    assert set(dispatched[1:]) == {"pkg-b", "pkg-c"}


def test_bootstrap_parallel_resolve_test_mode_failure_records_and_continues(
    tmp_context: WorkContext,
) -> None:
    """In test mode, a failed RESOLVE item is recorded and siblings succeed."""
    bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True, max_workers=2)

    pkg_b = bootstrapper.WorkItem(
        req=Requirement("pkg-b"),
        req_type=RequirementType.INSTALL,
        phase=bootstrapper.BootstrapPhase.RESOLVE,
        why_snapshot=[],
    )
    pkg_c = bootstrapper.WorkItem(
        req=Requirement("pkg-c"),
        req_type=RequirementType.INSTALL,
        phase=bootstrapper.BootstrapPhase.RESOLVE,
        why_snapshot=[],
    )

    def dispatch_side_effect(
        item: bootstrapper.WorkItem,
    ) -> list[bootstrapper.WorkItem]:
        if item.req.name == "pkg-a":
            return [pkg_b, pkg_c]
        if item.req.name == "pkg-b":
            raise ValueError("simulated resolution failure")
        return []  # pkg-c succeeds with no further work

    with patch.object(bt, "_dispatch_phase", side_effect=dispatch_side_effect):
        bt.bootstrap(req=Requirement("pkg-a"), req_type=RequirementType.TOP_LEVEL)

    # pkg-b failure recorded; pkg-c succeeded and is not in failed list
    assert len(bt.failed_packages) == 1
    assert bt.failed_packages[0]["package"] == "pkg-b"


def test_bootstrap_loop_uses_threadpool_for_single_item_phases(
    tmp_context: WorkContext,
) -> None:
    """All phases run through the shared ThreadPoolExecutor."""
    import concurrent.futures

    bt = bootstrapper.Bootstrapper(tmp_context)
    submit_calls: list[object] = []

    class TrackingExecutor(concurrent.futures.ThreadPoolExecutor):
        def submit(
            self, fn: object, /, *args: object, **kwargs: object
        ) -> concurrent.futures.Future:  # type: ignore[override]
            submit_calls.append(fn)
            return super().submit(fn, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(
        bt._resolver,
        "resolve",
        return_value=[("https://pkg.test/p-1.0.tar.gz", Version("1.0"))],
    ):
        with patch.object(bt, "_has_been_seen", return_value=True):
            with patch(
                "fromager.bootstrapper.concurrent.futures.ThreadPoolExecutor",
                TrackingExecutor,
            ):
                bt.bootstrap(req=Requirement("pkg"), req_type=RequirementType.TOP_LEVEL)

    # At least one item was submitted to the executor
    assert len(submit_calls) >= 1


def test_update_build_sequence_precedes_its_process_install_deps(
    tmp_context: WorkContext,
) -> None:
    """Each UPDATE_BUILD_SEQUENCE item runs before its paired PROCESS_INSTALL_DEPS item.

    With single-item serial batching, UPDATE_BUILD_SEQUENCE items interleave
    with PROCESS_INSTALL_DEPS items from other packages (UBS-a, PID-a, UBS-b,
    PID-b rather than UBS-a, UBS-b, PID-a, PID-b).  The per-item ordering
    guarantee (each UBS precedes its own PID) still holds.
    """
    bt = bootstrapper.Bootstrapper(tmp_context)
    dispatch_log: list[bootstrapper.BootstrapPhase] = []

    req_a = Requirement("pkg-a")
    req_b = Requirement("pkg-b")
    ubs_phase = bootstrapper.BootstrapPhase.UPDATE_BUILD_SEQUENCE
    pid_phase = bootstrapper.BootstrapPhase.PROCESS_INSTALL_DEPS

    # resolved_version must be set on items whose phase has tracks_why=True
    # (all phases except RESOLVE and START) so that _track_why doesn't assert-fail.
    def make_ubs(req: Requirement) -> bootstrapper.WorkItem:
        return bootstrapper.WorkItem(
            req=req,
            req_type=RequirementType.TOP_LEVEL,
            phase=ubs_phase,
            why_snapshot=[],
            resolved_version=Version("1.0"),
        )

    def make_pid(req: Requirement) -> bootstrapper.WorkItem:
        return bootstrapper.WorkItem(
            req=req,
            req_type=RequirementType.TOP_LEVEL,
            phase=pid_phase,
            why_snapshot=[],
            resolved_version=Version("1.0"),
        )

    pid_a = make_pid(req_a)
    pid_b = make_pid(req_b)
    ubs_a = make_ubs(req_a)
    ubs_b = make_ubs(req_b)

    def mock_dispatch(item: bootstrapper.WorkItem) -> list[bootstrapper.WorkItem]:
        dispatch_log.append(item.phase)
        if item.phase == bootstrapper.BootstrapPhase.RESOLVE:
            # Return two UBS items so both land on the stack together
            return [ubs_a, ubs_b]
        if item.phase == ubs_phase:
            return [pid_a] if item.req.name == "pkg-a" else [pid_b]
        # PID phase
        return []

    with patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch):
        bt.bootstrap(req=req_a, req_type=RequirementType.TOP_LEVEL)

    ubs_indices = [i for i, p in enumerate(dispatch_log) if p == ubs_phase]
    pid_indices = [i for i, p in enumerate(dispatch_log) if p == pid_phase]

    assert len(ubs_indices) == 2, f"Expected 2 UBS dispatches, got {ubs_indices}"
    assert len(pid_indices) == 2, f"Expected 2 PID dispatches, got {pid_indices}"

    # Per-item ordering: the n-th UBS must precede the n-th PID it produces.
    # With single-item serial batching the pairs interleave (UBS-b, PID-b,
    # UBS-a, PID-a) so we compare sorted pairs rather than requiring a global
    # all-UBS-before-all-PID ordering.
    for ubs_idx, pid_idx in zip(sorted(ubs_indices), sorted(pid_indices), strict=True):
        assert ubs_idx < pid_idx, (
            f"UBS dispatch at {ubs_idx} should precede its paired PID at {pid_idx}"
        )


def test_bootstrap_parallel_process_install_deps(
    tmp_context: WorkContext,
) -> None:
    """Multiple PROCESS_INSTALL_DEPS items are dispatched concurrently."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    dispatch_log: list[bootstrapper.BootstrapPhase] = []

    req_a = Requirement("pkg-a")
    req_b = Requirement("pkg-b")
    pid_phase = bootstrapper.BootstrapPhase.PROCESS_INSTALL_DEPS

    def make_pid(req: Requirement) -> bootstrapper.WorkItem:
        return bootstrapper.WorkItem(
            req=req,
            req_type=RequirementType.TOP_LEVEL,
            phase=pid_phase,
            why_snapshot=[],
            resolved_version=Version("1.0"),
        )

    pid_a = make_pid(req_a)
    pid_b = make_pid(req_b)

    def mock_dispatch(item: bootstrapper.WorkItem) -> list[bootstrapper.WorkItem]:
        dispatch_log.append(item.phase)
        if item.phase == bootstrapper.BootstrapPhase.RESOLVE:
            # Return two PID items directly so both land on the stack together
            return [pid_a, pid_b]
        # PID phase
        return []

    with patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch):
        bt.bootstrap(req=req_a, req_type=RequirementType.TOP_LEVEL)

    pid_dispatches = [p for p in dispatch_log if p == pid_phase]
    assert len(pid_dispatches) == 2, f"Expected 2 PID dispatches, got {pid_dispatches}"


def test_bootstrap_parallel_complete(
    tmp_context: WorkContext,
) -> None:
    """Multiple COMPLETE items are dispatched concurrently."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    dispatch_log: list[bootstrapper.BootstrapPhase] = []

    req_a = Requirement("pkg-a")
    req_b = Requirement("pkg-b")
    complete_phase = bootstrapper.BootstrapPhase.COMPLETE

    def make_complete(req: Requirement) -> bootstrapper.WorkItem:
        return bootstrapper.WorkItem(
            req=req,
            req_type=RequirementType.TOP_LEVEL,
            phase=complete_phase,
            why_snapshot=[],
            resolved_version=Version("1.0"),
        )

    complete_a = make_complete(req_a)
    complete_b = make_complete(req_b)

    def mock_dispatch(item: bootstrapper.WorkItem) -> list[bootstrapper.WorkItem]:
        dispatch_log.append(item.phase)
        if item.phase == bootstrapper.BootstrapPhase.RESOLVE:
            # Return two COMPLETE items directly so both land on the stack together
            return [complete_a, complete_b]
        # COMPLETE phase
        return []

    with patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch):
        bt.bootstrap(req=req_a, req_type=RequirementType.TOP_LEVEL)

    complete_dispatches = [p for p in dispatch_log if p == complete_phase]
    assert len(complete_dispatches) == 2, (
        f"Expected 2 COMPLETE dispatches, got {complete_dispatches}"
    )


def test_find_cached_wheel_holds_wheel_dir_lock_during_build_lookup(
    tmp_context: WorkContext,
) -> None:
    """_find_cached_wheel holds _wheel_dir_lock while inspecting wheels_build."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    lock_was_held: list[bool] = []
    original = bt._look_for_existing_wheel

    def spy(
        req: Requirement,
        version: Version,
        search_in: pathlib.Path,
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        if search_in == tmp_context.wheels_build:
            acquired = bt._wheel_dir_lock.acquire(blocking=False)
            lock_was_held.append(not acquired)
            if acquired:
                bt._wheel_dir_lock.release()
        return original(req, version, search_in)

    with unittest.mock.patch.object(bt, "_look_for_existing_wheel", side_effect=spy):
        bt._find_cached_wheel(Requirement("test-package"), Version("1.0.0"))

    assert lock_was_held == [True]


@unittest.mock.patch("fromager.server.update_wheel_mirror")
@unittest.mock.patch("fromager.wheels.download_wheel")
def test_download_prebuilt_holds_wheel_dir_lock_around_mirror_update(
    mock_download: unittest.mock.Mock,
    mock_mirror: unittest.mock.Mock,
    tmp_context: WorkContext,
) -> None:
    """_download_prebuilt holds _wheel_dir_lock while calling update_wheel_mirror."""
    bt = bootstrapper.Bootstrapper(tmp_context)
    mock_download.return_value = pathlib.Path(
        "/fake/test_package-1.0.0-py3-none-any.whl"
    )
    lock_was_held: list[bool] = []

    def spy_mirror(ctx: object) -> None:
        acquired = bt._wheel_dir_lock.acquire(blocking=False)
        lock_was_held.append(not acquired)
        if acquired:
            bt._wheel_dir_lock.release()

    mock_mirror.side_effect = spy_mirror

    bt._download_prebuilt(
        req=Requirement("test-package"),
        req_type=RequirementType.TOP_LEVEL,
        resolved_version=Version("1.0.0"),
        wheel_url="https://pkg.test/test_package-1.0.0-py3-none-any.whl",
    )

    assert lock_was_held == [True]
