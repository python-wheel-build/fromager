"""Tests for the iterative bootstrap implementation.

Tests cover:
- BootstrapPhase enum and tracks_why property
- WorkItem dataclass defaults and state accumulation
- _track_why context manager behavior
- _create_unresolved_work_items helper
- _phase_resolve version expansion
- _phase_start graph addition and seen-check
- _phase_complete cleanup
- _dispatch_phase routing
- _handle_phase_error for all three error modes
- End-to-end iterative loop with LIFO ordering
"""

from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper
from fromager.bootstrapper import BootstrapPhase, SourceBuildResult, WorkItem
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType, SourceType


def _make_resolve_item(
    req: str = "testpkg",
    req_type: RequirementType = RequirementType.INSTALL,
    why_snapshot: list | None = None,
    parent: tuple | None = None,
) -> WorkItem:
    return WorkItem(
        req=Requirement(req),
        req_type=req_type,
        phase=BootstrapPhase.RESOLVE,
        why_snapshot=why_snapshot or [],
        parent=parent,
    )


def _make_start_item(
    req: str = "testpkg",
    req_type: RequirementType = RequirementType.INSTALL,
    source_url: str = "https://pypi.org/testpkg-1.0.tar.gz",
    version: str = "1.0",
    why_snapshot: list | None = None,
    parent: tuple | None = None,
) -> WorkItem:
    return WorkItem(
        req=Requirement(req),
        req_type=req_type,
        phase=BootstrapPhase.START,
        why_snapshot=why_snapshot or [],
        parent=parent,
        source_url=source_url,
        resolved_version=Version(version),
    )


def _make_build_item(
    req: str = "testpkg",
    version: str = "1.0",
    phase: BootstrapPhase = BootstrapPhase.PREPARE_SOURCE,
) -> WorkItem:
    return WorkItem(
        req=Requirement(req),
        req_type=RequirementType.INSTALL,
        phase=phase,
        why_snapshot=[],
        source_url="https://pypi.org/testpkg-1.0.tar.gz",
        resolved_version=Version(version),
    )


class TestBootstrapPhase:
    def test_tracks_why_false_for_resolve(self) -> None:
        assert BootstrapPhase.RESOLVE.tracks_why is False

    def test_tracks_why_false_for_start(self) -> None:
        assert BootstrapPhase.START.tracks_why is False

    def test_tracks_why_true_for_build_phases(self) -> None:
        for phase in (
            BootstrapPhase.PREPARE_SOURCE,
            BootstrapPhase.PREPARE_BUILD,
            BootstrapPhase.BUILD,
            BootstrapPhase.PROCESS_INSTALL_DEPS,
            BootstrapPhase.COMPLETE,
        ):
            assert phase.tracks_why is True, f"{phase} should track why"


class TestWorkItem:
    def test_defaults_for_resolve_item(self) -> None:
        item = _make_resolve_item()
        assert item.source_url is None
        assert item.resolved_version is None
        assert item.build_sdist_only is False
        assert item.build_env is None
        assert item.build_result is None
        assert item.pbi_pre_built is False
        assert item.build_system_deps == set()
        assert item.build_backend_deps == set()
        assert item.build_sdist_deps == set()

    def test_state_accumulation(self) -> None:
        item = _make_start_item()
        item.pbi_pre_built = True
        item.build_sdist_only = True
        mock_env = Mock()
        item.build_env = mock_env
        assert item.pbi_pre_built is True
        assert item.build_sdist_only is True
        assert item.build_env is mock_env


class TestTrackWhy:
    def test_noop_for_resolve_phase(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = [(RequirementType.TOP_LEVEL, Requirement("parent"), Version("1.0"))]
        item = _make_resolve_item()

        with bt._track_why(item):
            assert len(bt.why) == 1

        assert len(bt.why) == 1

    def test_noop_for_start_phase(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item()

        with bt._track_why(item):
            assert len(bt.why) == 0

        assert len(bt.why) == 0

    def test_pushes_and_pops_for_build_phase(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)

        with bt._track_why(item):
            assert len(bt.why) == 1
            assert bt.why[0][1] == item.req
            assert bt.why[0][2] == item.resolved_version

        assert len(bt.why) == 0

    def test_pops_on_exception(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_build_item(phase=BootstrapPhase.BUILD)

        with pytest.raises(ValueError, match="boom"):
            with bt._track_why(item):
                assert len(bt.why) == 1
                raise ValueError("boom")

        assert len(bt.why) == 0


class TestCreateUnresolvedWorkItems:
    def test_creates_resolve_phase_items(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        deps = [Requirement("dep-a"), Requirement("dep-b")]

        items = bt._create_unresolved_work_items(
            deps, RequirementType.BUILD_SYSTEM, Requirement("parent"), Version("1.0")
        )

        assert len(items) == 2
        for item in items:
            assert item.phase == BootstrapPhase.RESOLVE
            assert item.req_type == RequirementType.BUILD_SYSTEM
            assert item.parent == (Requirement("parent"), Version("1.0"))
            assert item.source_url is None
            assert item.resolved_version is None

    def test_captures_why_snapshot(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = [(RequirementType.TOP_LEVEL, Requirement("root"), Version("2.0"))]

        items = bt._create_unresolved_work_items(
            [Requirement("dep")],
            RequirementType.INSTALL,
            Requirement("parent"),
            Version("1.0"),
        )

        assert len(items) == 1
        assert items[0].why_snapshot == bt.why
        # Verify it's a copy, not a reference
        bt.why.append((RequirementType.INSTALL, Requirement("other"), Version("3.0")))
        assert len(items[0].why_snapshot) == 1

    def test_sorts_by_name(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        deps = [Requirement("zebra"), Requirement("alpha"), Requirement("middle")]

        items = bt._create_unresolved_work_items(
            deps, RequirementType.INSTALL, Requirement("p"), Version("1.0")
        )

        names = [str(item.req.name) for item in items]
        assert names == ["alpha", "middle", "zebra"]

    def test_empty_deps(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        items = bt._create_unresolved_work_items(
            [], RequirementType.INSTALL, Requirement("p"), Version("1.0")
        )
        assert items == []


class TestPhaseResolve:
    def test_single_version(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_resolve_item()
        parent = (Requirement("parent"), Version("2.0"))
        item.parent = parent

        with patch.object(
            bt,
            "resolve_versions",
            return_value=[("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0"))],
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 1
        assert result[0].phase == BootstrapPhase.START
        assert result[0].source_url == "https://pypi.org/testpkg-1.0.tar.gz"
        assert result[0].resolved_version == Version("1.0")
        assert result[0].parent == parent

    def test_multiple_versions(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()

        with patch.object(
            bt,
            "resolve_versions",
            return_value=[
                ("https://pypi.org/testpkg-2.0.tar.gz", Version("2.0")),
                ("https://pypi.org/testpkg-1.0.tar.gz", Version("1.0")),
            ],
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 2
        # Reversed so highest version ends up on top of stack (last element)
        assert result[0].resolved_version == Version("1.0")
        assert result[1].resolved_version == Version("2.0")

    def test_empty_resolution_raises(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_resolve_item()

        with patch.object(bt, "resolve_versions", return_value=[]):
            with pytest.raises(RuntimeError, match="Could not resolve"):
                bt._phase_resolve(item)

    def test_preserves_why_snapshot(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        snapshot = [(RequirementType.TOP_LEVEL, Requirement("root"), Version("1.0"))]
        item = _make_resolve_item(why_snapshot=list(snapshot))

        with patch.object(
            bt,
            "resolve_versions",
            return_value=[("url", Version("1.0"))],
        ):
            result = bt._phase_resolve(item)

        assert result[0].why_snapshot == snapshot

    def test_filters_cached_versions_in_multiple_versions_mode(
        self, tmp_context: WorkContext
    ) -> None:
        """Cached versions are filtered out before creating START items."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()

        def mock_cache(req: Requirement, version: Version) -> tuple:
            if str(version) == "2.0":
                return (tmp_context.work_dir / "pkg-2.0-py3-none-any.whl", None)
            return (None, None)

        with (
            patch.object(
                bt,
                "resolve_versions",
                return_value=[
                    ("url-3.0", Version("3.0")),
                    ("url-2.0", Version("2.0")),
                    ("url-1.0", Version("1.0")),
                ],
            ),
            patch.object(bt, "_find_cached_wheel", side_effect=mock_cache),
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 2
        versions = {str(it.resolved_version) for it in result}
        assert versions == {"1.0", "3.0"}

    def test_all_cached_keeps_highest_version(self, tmp_context: WorkContext) -> None:
        """If all versions are cached, keeps the highest for dependency discovery."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()

        with (
            patch.object(
                bt,
                "resolve_versions",
                return_value=[
                    ("url-3.0", Version("3.0")),
                    ("url-2.0", Version("2.0")),
                    ("url-1.0", Version("1.0")),
                ],
            ),
            patch.object(
                bt,
                "_find_cached_wheel",
                return_value=(tmp_context.work_dir / "cached.whl", None),
            ),
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 1
        assert result[0].resolved_version == Version("3.0")

    def test_no_filtering_in_single_version_mode(
        self, tmp_context: WorkContext
    ) -> None:
        """Cache filtering does not apply in single version mode."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=False)
        item = _make_resolve_item()

        with (
            patch.object(
                bt,
                "resolve_versions",
                return_value=[("url-1.0", Version("1.0"))],
            ),
            patch.object(bt, "_find_cached_wheel") as mock_cache,
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 1
        mock_cache.assert_not_called()

    def test_empty_resolution_raises_runtime_error(
        self, tmp_context: WorkContext
    ) -> None:
        """Empty resolution raises RuntimeError regardless of mode."""
        for multi in (False, True):
            bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=multi)
            item = _make_resolve_item()

            with (
                patch.object(bt, "resolve_versions", return_value=[]),
                pytest.raises(RuntimeError, match="Could not resolve"),
            ):
                bt._phase_resolve(item)


class TestPhaseStart:
    def test_new_item_advances_to_prepare_source(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item()

        result = bt._phase_start(item)

        assert len(result) == 1
        assert result[0].phase == BootstrapPhase.PREPARE_SOURCE
        assert result[0] is item

    def test_already_seen_returns_empty(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item()

        # Mark as seen first
        assert item.resolved_version is not None
        bt._mark_as_seen(item.req, item.resolved_version)

        result = bt._phase_start(item)

        assert result == []

    def test_adds_to_graph_for_non_toplevel(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item(req_type=RequirementType.INSTALL)

        bt._phase_start(item)

        key = f"{canonicalize_name('testpkg')}==1.0"
        assert key in tmp_context.dependency_graph.nodes

    def test_skips_graph_for_toplevel(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item(req_type=RequirementType.TOP_LEVEL)

        bt._phase_start(item)

        key = f"{canonicalize_name('testpkg')}==1.0"
        assert key not in tmp_context.dependency_graph.nodes

    def test_sdist_only_set_for_non_build_requirement(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, sdist_only=True)
        bt.why = []
        item = _make_start_item(req_type=RequirementType.INSTALL)

        bt._phase_start(item)

        assert item.build_sdist_only is True

    def test_sdist_only_not_set_for_build_requirement(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, sdist_only=True)
        bt.why = []
        item = _make_start_item(req_type=RequirementType.BUILD_SYSTEM)

        bt._phase_start(item)

        assert item.build_sdist_only is False

    def test_marks_as_seen(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        bt.why = []
        item = _make_start_item()
        assert item.resolved_version is not None

        assert not bt._has_been_seen(item.req, item.resolved_version)
        bt._phase_start(item)
        assert bt._has_been_seen(item.req, item.resolved_version)


class TestPhaseComplete:
    def test_calls_clean_build_dirs(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_sdist_root = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
        mock_env = Mock()
        build_result = SourceBuildResult(
            wheel_filename=None,
            sdist_filename=None,
            unpack_dir=tmp_context.work_dir,
            sdist_root_dir=mock_sdist_root,
            build_env=mock_env,
            source_type=SourceType.SDIST,
        )
        item = _make_build_item(phase=BootstrapPhase.COMPLETE)
        item.build_result = build_result

        with patch.object(tmp_context, "clean_build_dirs") as mock_clean:
            result = bt._phase_complete(item)

        assert result == []
        mock_clean.assert_called_once_with(mock_sdist_root, mock_env)

    def test_no_build_result_skips_cleanup(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.COMPLETE)
        item.build_result = None

        with patch.object(tmp_context, "clean_build_dirs") as mock_clean:
            result = bt._phase_complete(item)

        assert result == []
        mock_clean.assert_not_called()


class TestDispatchPhase:
    @pytest.mark.parametrize(
        "phase,method_name",
        [
            (BootstrapPhase.RESOLVE, "_phase_resolve"),
            (BootstrapPhase.START, "_phase_start"),
            (BootstrapPhase.PREPARE_SOURCE, "_phase_prepare_source"),
            (BootstrapPhase.PREPARE_BUILD, "_phase_prepare_build"),
            (BootstrapPhase.BUILD, "_phase_build"),
            (BootstrapPhase.PROCESS_INSTALL_DEPS, "_phase_process_install_deps"),
            (BootstrapPhase.COMPLETE, "_phase_complete"),
        ],
    )
    def test_routes_to_correct_handler(
        self, tmp_context: WorkContext, phase: BootstrapPhase, method_name: str
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=phase)
        expected = [item]

        with patch.object(bt, method_name, return_value=expected) as mock_method:
            result = bt._dispatch_phase(item)

        assert result is expected
        mock_method.assert_called_once_with(item)


class TestHandlePhaseError:
    # -- RESOLVE phase errors --

    def test_resolve_error_in_test_mode_records_failure(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = _make_resolve_item()
        err = RuntimeError("resolution failed")

        result = bt._handle_phase_error(item, err)

        assert result == []
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "resolution"
        assert bt.failed_packages[0]["version"] is None

    def test_resolve_error_in_normal_mode_raises(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_resolve_item()
        err = RuntimeError("resolution failed")

        with pytest.raises(RuntimeError, match="resolution failed"):
            try:
                raise err
            except RuntimeError:
                bt._handle_phase_error(item, err)

    def test_resolve_error_in_multiple_versions_mode_raises(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()
        err = RuntimeError("resolution failed")

        with pytest.raises(RuntimeError, match="resolution failed"):
            try:
                raise err
            except RuntimeError:
                bt._handle_phase_error(item, err)

    # -- Build phase errors in test mode --

    def test_build_phase_test_mode_fallback_success(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)
        item.pbi_pre_built = False
        err = RuntimeError("build failed")

        mock_fallback = Mock(spec=SourceBuildResult)
        with patch.object(bt, "_handle_test_mode_failure", return_value=mock_fallback):
            result = bt._handle_phase_error(item, err)

        assert len(result) == 1
        assert result[0] is item
        assert item.build_result is mock_fallback
        assert item.phase == BootstrapPhase.PROCESS_INSTALL_DEPS
        assert len(bt.failed_packages) == 0

    def test_build_phase_test_mode_fallback_failure(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = _make_build_item(phase=BootstrapPhase.BUILD)
        item.pbi_pre_built = False
        err = RuntimeError("build failed")

        with patch.object(bt, "_handle_test_mode_failure", return_value=None):
            result = bt._handle_phase_error(item, err)

        assert result == []
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "bootstrap"

    def test_build_phase_test_mode_prebuilt_skips_fallback(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)
        item.pbi_pre_built = True
        err = RuntimeError("download failed")

        result = bt._handle_phase_error(item, err)

        assert result == []
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "bootstrap"

    def test_non_build_phase_test_mode_records_failure(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = _make_build_item(phase=BootstrapPhase.PROCESS_INSTALL_DEPS)
        err = RuntimeError("hook failed")

        result = bt._handle_phase_error(item, err)

        assert result == []
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "bootstrap"

    # -- Multiple versions mode errors --

    def test_multiple_versions_records_and_removes_from_graph(
        self, tmp_context: WorkContext
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_build_item(phase=BootstrapPhase.BUILD)
        assert item.resolved_version is not None
        assert item.source_url is not None
        err = ValueError("build failed")

        # Add to graph first so remove_dependency has something to remove
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=item.req,
            req_version=item.resolved_version,
            download_url=item.source_url,
            pre_built=False,
        )
        # Mark as seen
        bt._mark_as_seen(item.req, item.resolved_version)

        result = bt._handle_phase_error(item, err)

        assert result == []
        # Failure recorded
        assert len(bt._failed_versions) == 1
        assert bt._failed_versions[0][0] == canonicalize_name("testpkg")
        assert bt._failed_versions[0][1] == "1.0"
        # Removed from graph
        key = f"{canonicalize_name('testpkg')}==1.0"
        assert key not in tmp_context.dependency_graph.nodes
        # Seen markers cleared
        assert not bt._has_been_seen(item.req, item.resolved_version)
        assert not bt._has_been_seen(item.req, item.resolved_version, sdist_only=True)

    def test_multiple_versions_logs_phase(
        self, tmp_context: WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_BUILD)
        err = ValueError("compile error")

        bt._handle_phase_error(item, err)

        assert "prepare-build phase" in caplog.text
        assert "compile error" in caplog.text

    # -- Normal mode errors --

    def test_normal_mode_raises(self, tmp_context: WorkContext) -> None:
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.BUILD)
        err = RuntimeError("build failed")

        with pytest.raises(RuntimeError, match="build failed"):
            try:
                raise err
            except RuntimeError:
                bt._handle_phase_error(item, err)


class TestIterativeBootstrapLoop:
    def test_full_lifecycle_source_package(self, tmp_context: WorkContext) -> None:
        """Drive a package through RESOLVE -> START -> ... -> COMPLETE."""
        bt = bootstrapper.Bootstrapper(tmp_context)

        # Track which phases are visited
        phases_visited: list[BootstrapPhase] = []
        original_dispatch = bt._dispatch_phase

        def tracking_dispatch(item: WorkItem) -> list[WorkItem]:
            phases_visited.append(item.phase)
            if item.phase == BootstrapPhase.RESOLVE:
                return original_dispatch(item)
            if item.phase == BootstrapPhase.START:
                return original_dispatch(item)
            if item.phase == BootstrapPhase.PREPARE_SOURCE:
                # Skip actual source download, simulate source build path
                item.phase = BootstrapPhase.PREPARE_BUILD
                item.build_env = Mock()
                item.sdist_root_dir = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
                return [item]
            if item.phase == BootstrapPhase.PREPARE_BUILD:
                item.phase = BootstrapPhase.BUILD
                return [item]
            if item.phase == BootstrapPhase.BUILD:
                item.build_result = SourceBuildResult(
                    wheel_filename=None,
                    sdist_filename=None,
                    unpack_dir=tmp_context.work_dir,
                    sdist_root_dir=None,
                    build_env=None,
                    source_type=SourceType.SDIST,
                )
                item.phase = BootstrapPhase.PROCESS_INSTALL_DEPS
                return [item]
            if item.phase == BootstrapPhase.PROCESS_INSTALL_DEPS:
                item.phase = BootstrapPhase.COMPLETE
                return [item]
            if item.phase == BootstrapPhase.COMPLETE:
                return []
            return []

        with (
            patch.object(bt, "_dispatch_phase", side_effect=tracking_dispatch),
            patch.object(
                bt,
                "resolve_versions",
                return_value=[("https://pypi.org/pkg-1.0.tar.gz", Version("1.0"))],
            ),
        ):
            bt.bootstrap(Requirement("pkg"), RequirementType.TOP_LEVEL)

        assert phases_visited == [
            BootstrapPhase.RESOLVE,
            BootstrapPhase.START,
            BootstrapPhase.PREPARE_SOURCE,
            BootstrapPhase.PREPARE_BUILD,
            BootstrapPhase.BUILD,
            BootstrapPhase.PROCESS_INSTALL_DEPS,
            BootstrapPhase.COMPLETE,
        ]

    def test_lifo_ordering_deps_before_continuation(
        self, tmp_context: WorkContext
    ) -> None:
        """Verify dependencies are processed before the parent continues."""
        bt = bootstrapper.Bootstrapper(tmp_context)

        processing_order: list[tuple[str, str]] = []
        original_dispatch = bt._dispatch_phase

        def tracking_dispatch(item: WorkItem) -> list[WorkItem]:
            phase_name = str(item.phase)
            req_name = str(item.req.name)
            processing_order.append((req_name, phase_name))

            if item.phase == BootstrapPhase.RESOLVE:
                return original_dispatch(item)
            if item.phase == BootstrapPhase.START:
                return original_dispatch(item)

            # Parent discovers a dep at PREPARE_SOURCE
            if req_name == "parent" and item.phase == BootstrapPhase.PREPARE_SOURCE:
                assert item.resolved_version is not None
                dep_item = WorkItem(
                    req=Requirement("child"),
                    req_type=RequirementType.BUILD_SYSTEM,
                    phase=BootstrapPhase.RESOLVE,
                    why_snapshot=[],
                    parent=(item.req, item.resolved_version),
                )
                item.phase = BootstrapPhase.COMPLETE
                return [item, dep_item]

            return []

        # Pre-add parent to graph so child can reference it as parent
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement("parent"),
            req_version=Version("1.0"),
            download_url="https://pypi.org/pkg-1.0.tar.gz",
            pre_built=False,
        )

        with (
            patch.object(bt, "_dispatch_phase", side_effect=tracking_dispatch),
            patch.object(
                bt,
                "resolve_versions",
                return_value=[("https://pypi.org/pkg-1.0.tar.gz", Version("1.0"))],
            ),
        ):
            bt.bootstrap(Requirement("parent"), RequirementType.TOP_LEVEL)

        # child's RESOLVE and START must appear before parent's COMPLETE
        req_phase_pairs = [
            (name, phase)
            for name, phase in processing_order
            if name in ("parent", "child")
        ]

        parent_complete_idx = next(
            i
            for i, (n, p) in enumerate(req_phase_pairs)
            if n == "parent" and p == "complete"
        )
        child_indices = [i for i, (n, _) in enumerate(req_phase_pairs) if n == "child"]

        assert all(idx < parent_complete_idx for idx in child_indices), (
            f"child must be processed before parent completes: {req_phase_pairs}"
        )

    def test_multiple_versions_error_isolation(self, tmp_context: WorkContext) -> None:
        """Each version fails independently without crashing the loop."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)

        original_dispatch = bt._dispatch_phase

        def mock_dispatch(item: WorkItem) -> list[WorkItem]:
            if item.phase in (BootstrapPhase.RESOLVE, BootstrapPhase.START):
                return original_dispatch(item)
            # Fail version 1.5, succeed for others
            if str(item.resolved_version) == "1.5":
                raise ValueError("1.5 broken")
            return []

        with (
            patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch),
            patch.object(
                bt._resolver,
                "resolve",
                return_value=[
                    ("url-2.0", Version("2.0")),
                    ("url-1.5", Version("1.5")),
                    ("url-1.0", Version("1.0")),
                ],
            ),
            patch.object(bt, "_has_been_seen", return_value=False),
        ):
            bt.bootstrap(Requirement("pkg"), RequirementType.INSTALL)

        assert len(bt._failed_versions) == 1
        assert bt._failed_versions[0][1] == "1.5"
        # Other versions processed successfully (in graph)
        assert f"{canonicalize_name('pkg')}==2.0" in tmp_context.dependency_graph.nodes
        assert f"{canonicalize_name('pkg')}==1.0" in tmp_context.dependency_graph.nodes

    def test_test_mode_continues_after_failure(self, tmp_context: WorkContext) -> None:
        """In test mode, failed items are recorded and processing continues."""
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)

        original_dispatch = bt._dispatch_phase
        items_completed: list[str] = []

        def mock_dispatch(item: WorkItem) -> list[WorkItem]:
            if item.phase in (BootstrapPhase.RESOLVE, BootstrapPhase.START):
                return original_dispatch(item)
            if str(item.req.name) == "fail-pkg":
                raise RuntimeError("build error")
            items_completed.append(str(item.req.name))
            return []

        with (
            patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch),
            patch.object(
                bt,
                "resolve_versions",
                return_value=[("url", Version("1.0"))],
            ),
        ):
            # Bootstrap a package that will fail
            bt.bootstrap(Requirement("fail-pkg"), RequirementType.TOP_LEVEL)
            # Bootstrap another that will succeed
            bt.bootstrap(Requirement("ok-pkg"), RequirementType.TOP_LEVEL)

        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["package"] == "fail-pkg"
        assert "ok-pkg" in items_completed
