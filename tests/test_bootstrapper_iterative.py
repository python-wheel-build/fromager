"""Tests for the iterative bootstrap implementation.

Tests cover:
- BootstrapPhase enum and tracks_why property
- WorkItem dataclass defaults and state accumulation
- _track_why context manager behavior
- _create_unresolved_work_items helper
- _phase_resolve version expansion
- _phase_start graph addition and seen-check
- _phase_prepare_source all branches (prebuilt, source, cached, bad path)
- _phase_prepare_build dep installation and extraction
- _phase_build conditional install and result construction
- _phase_process_install_deps hooks, dep extraction, error modes
- _phase_complete cleanup
- _dispatch_phase routing
- _handle_phase_error for all three error modes
- End-to-end iterative loop with LIFO ordering
"""

from __future__ import annotations

import pathlib
from unittest.mock import Mock, call, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper, build_environment
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
    source_url: str = "https://pypi.org/testpkg-1.0.tar.gz",
    build_env: build_environment.BuildEnvironment | None = None,
    sdist_root_dir: pathlib.Path | None = None,
    unpack_dir: pathlib.Path | None = None,
    build_result: SourceBuildResult | None = None,
    build_system_deps: set[Requirement] | None = None,
    build_backend_deps: set[Requirement] | None = None,
    build_sdist_deps: set[Requirement] | None = None,
    pbi_pre_built: bool = False,
    cached_wheel_filename: pathlib.Path | None = None,
    build_sdist_only: bool = False,
) -> WorkItem:
    return WorkItem(
        req=Requirement(req),
        req_type=RequirementType.INSTALL,
        phase=phase,
        why_snapshot=[],
        source_url=source_url,
        resolved_version=Version(version),
        build_env=build_env,
        sdist_root_dir=sdist_root_dir,
        unpack_dir=unpack_dir,
        build_result=build_result,
        build_system_deps=build_system_deps if build_system_deps is not None else set(),
        build_backend_deps=build_backend_deps
        if build_backend_deps is not None
        else set(),
        build_sdist_deps=build_sdist_deps if build_sdist_deps is not None else set(),
        pbi_pre_built=pbi_pre_built,
        cached_wheel_filename=cached_wheel_filename,
        build_sdist_only=build_sdist_only,
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

    def test_filters_failed_versions_in_multiple_versions_mode(
        self, tmp_context: WorkContext
    ) -> None:
        """Previously failed versions are excluded before creating START items."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()

        bt._failed_versions[(canonicalize_name("testpkg"), "2.0")] = RuntimeError(
            "boom"
        )

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
            patch.object(bt, "_find_cached_wheel", return_value=(None, None)),
        ):
            result = bt._phase_resolve(item)

        versions = {str(it.resolved_version) for it in result}
        assert versions == {"1.0", "3.0"}

    def test_failed_version_filter_does_not_apply_in_single_version_mode(
        self, tmp_context: WorkContext
    ) -> None:
        """Failed-version filtering only applies in multiple_versions mode."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=False)
        item = _make_resolve_item()

        bt._failed_versions[(canonicalize_name("testpkg"), "1.0")] = RuntimeError(
            "boom"
        )

        with patch.object(
            bt,
            "resolve_versions",
            return_value=[("url-1.0", Version("1.0"))],
        ):
            result = bt._phase_resolve(item)

        assert len(result) == 1
        assert result[0].resolved_version == Version("1.0")

    def test_all_versions_failed_raises_runtime_error(
        self, tmp_context: WorkContext
    ) -> None:
        """Raises RuntimeError when all resolved versions already failed."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()

        bt._failed_versions[(canonicalize_name("testpkg"), "1.0")] = RuntimeError(
            "boom"
        )

        with (
            patch.object(
                bt,
                "resolve_versions",
                return_value=[("url-1.0", Version("1.0"))],
            ),
            pytest.raises(RuntimeError, match="failed previously"),
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

    def test_resolve_error_in_multiple_versions_mode_continues(
        self, tmp_context: WorkContext
    ) -> None:
        """RESOLVE failures in multiple versions mode are recorded, not raised."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)
        item = _make_resolve_item()
        err = RuntimeError("resolution failed")

        try:
            raise err
        except RuntimeError:
            result = bt._handle_phase_error(item, err)

        assert result == []
        assert len(bt._failed_versions) == 1
        key = (canonicalize_name("testpkg"), "unresolved")
        assert key in bt._failed_versions
        assert bt._failed_versions[key] is err

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
        assert (canonicalize_name("testpkg"), "1.0") in bt._failed_versions
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
        assert (canonicalize_name("pkg"), "1.5") in bt._failed_versions
        # Other versions processed successfully (in graph)
        assert f"{canonicalize_name('pkg')}==2.0" in tmp_context.dependency_graph.nodes
        assert f"{canonicalize_name('pkg')}==1.0" in tmp_context.dependency_graph.nodes

    def test_multiple_versions_resolve_failure_continues(
        self, tmp_context: WorkContext
    ) -> None:
        """RESOLVE failure for one dependency does not crash the loop."""
        bt = bootstrapper.Bootstrapper(tmp_context, multiple_versions=True)

        original_dispatch = bt._dispatch_phase
        completed: list[str] = []

        def mock_dispatch(item: WorkItem) -> list[WorkItem]:
            if item.phase == BootstrapPhase.START:
                return original_dispatch(item)
            if item.phase == BootstrapPhase.RESOLVE:
                if str(item.req.name) == "bad-dep":
                    raise RuntimeError("Could not resolve any versions for bad-dep")
                return original_dispatch(item)
            completed.append(str(item.req.name))
            return []

        with (
            patch.object(bt, "_dispatch_phase", side_effect=mock_dispatch),
            patch.object(
                bt._resolver,
                "resolve",
                return_value=[("url-1.0", Version("1.0"))],
            ),
            patch.object(bt, "_has_been_seen", return_value=False),
        ):
            bt.bootstrap(Requirement("good-pkg"), RequirementType.INSTALL)
            bt.bootstrap(Requirement("bad-dep"), RequirementType.INSTALL)
            bt.bootstrap(Requirement("another-good"), RequirementType.INSTALL)

        assert "good-pkg" in completed
        assert "another-good" in completed
        failed_names = [name for name, _ in bt._failed_versions]
        assert canonicalize_name("bad-dep") in failed_names

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


class TestPhasePrepareSource:
    """Tests for _phase_prepare_source: prebuilt, source, cache, and error paths."""

    def test_prebuilt_downloads_and_skips_to_process_install_deps(
        self, tmp_context: WorkContext
    ) -> None:
        """Prebuilt package downloads wheel and advances to PROCESS_INSTALL_DEPS."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_SOURCE,
            pbi_pre_built=True,
            source_url="https://pkg.test/testpkg-1.0-py3-none-any.whl",
        )

        mock_wheel = tmp_context.work_dir / "testpkg-1.0-py3-none-any.whl"
        mock_unpack = tmp_context.work_dir / "testpkg-1.0"

        with (
            patch.object(
                bt, "_download_prebuilt", return_value=(mock_wheel, mock_unpack)
            ) as mock_dl,
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
        ):
            result = bt._phase_prepare_source(item)

        assert len(result) == 1
        assert result[0] is item
        assert item.phase == BootstrapPhase.PROCESS_INSTALL_DEPS
        assert item.build_result is not None
        assert item.build_result.source_type == SourceType.PREBUILT
        assert item.build_result.wheel_filename == mock_wheel
        assert item.build_result.sdist_filename is None
        assert item.build_result.build_env is None
        mock_dl.assert_called_once()

    def test_source_no_cache_downloads_and_prepares(
        self, tmp_context: WorkContext
    ) -> None:
        """Source build with no cached wheel downloads and prepares source."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)

        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        source_filename = tmp_context.work_dir / "testpkg-1.0.tar.gz"
        mock_env = Mock()
        mock_dep_item = _make_resolve_item(req="setuptools")

        with (
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_find_cached_wheel", return_value=(None, None)),
            patch.object(
                bt, "_download_source", return_value=source_filename
            ) as mock_dl_src,
            patch.object(bt, "_prepare_source", return_value=sdist_root) as mock_prep,
            patch.object(
                bt, "_create_build_env", return_value=mock_env
            ) as mock_create_env,
            patch(
                "fromager.dependencies.get_build_system_dependencies",
                return_value={Requirement("setuptools")},
            ),
            patch.object(
                bt, "_create_unresolved_work_items", return_value=[mock_dep_item]
            ) as mock_create_items,
        ):
            result = bt._phase_prepare_source(item)

        assert item.phase == BootstrapPhase.PREPARE_BUILD
        assert item.build_env is mock_env
        assert item.sdist_root_dir == sdist_root
        assert item.unpack_dir == sdist_root.parent
        assert result[0] is item
        assert result[1] is mock_dep_item
        mock_dl_src.assert_called_once()
        mock_prep.assert_called_once()
        mock_create_env.assert_called_once()
        mock_create_items.assert_called_once_with(
            item.build_system_deps,
            RequirementType.BUILD_SYSTEM,
            item.req,
            item.resolved_version,
        )

    def test_source_cached_wheel_skips_download(self, tmp_context: WorkContext) -> None:
        """Cached wheel skips download/prepare, uses unpacked dir for sdist root."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)

        unpacked = tmp_context.work_dir / "testpkg-1.0"
        unpacked.mkdir(parents=True)
        cached_wheel = tmp_context.work_dir / "testpkg-1.0-py3-none-any.whl"
        mock_env = Mock()

        with (
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(
                bt, "_find_cached_wheel", return_value=(cached_wheel, unpacked)
            ),
            patch.object(bt, "_download_source") as mock_dl_src,
            patch.object(bt, "_prepare_source") as mock_prep,
            patch.object(bt, "_create_build_env", return_value=mock_env),
            patch(
                "fromager.dependencies.get_build_system_dependencies",
                return_value=set(),
            ),
            patch.object(bt, "_create_unresolved_work_items", return_value=[]),
        ):
            result = bt._phase_prepare_source(item)

        assert item.cached_wheel_filename == cached_wheel
        assert item.sdist_root_dir == unpacked / unpacked.stem
        assert item.phase == BootstrapPhase.PREPARE_BUILD
        mock_dl_src.assert_not_called()
        mock_prep.assert_not_called()
        assert len(result) == 1

    def test_bad_sdist_root_raises_valueerror(self, tmp_context: WorkContext) -> None:
        """ValueError raised when sdist_root_dir.parent.parent != work_dir."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)

        bad_root = tmp_context.work_dir / "a" / "b" / "c"

        with (
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_find_cached_wheel", return_value=(None, None)),
            patch.object(
                bt,
                "_download_source",
                return_value=tmp_context.work_dir / "src.tar.gz",
            ),
            patch.object(bt, "_prepare_source", return_value=bad_root),
        ):
            with pytest.raises(ValueError, match="should be"):
                bt._phase_prepare_source(item)

    def test_constraint_logged_when_present(
        self, tmp_context: WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Constraint presence is logged without affecting phase advancement."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(phase=BootstrapPhase.PREPARE_SOURCE)

        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        mock_env = Mock()

        with (
            patch.object(
                tmp_context.constraints,
                "get_constraint",
                return_value=Requirement("testpkg>=1.0"),
            ),
            patch.object(bt, "_find_cached_wheel", return_value=(None, None)),
            patch.object(
                bt,
                "_download_source",
                return_value=tmp_context.work_dir / "src.tar.gz",
            ),
            patch.object(bt, "_prepare_source", return_value=sdist_root),
            patch.object(bt, "_create_build_env", return_value=mock_env),
            patch(
                "fromager.dependencies.get_build_system_dependencies",
                return_value=set(),
            ),
            patch.object(bt, "_create_unresolved_work_items", return_value=[]),
        ):
            bt._phase_prepare_source(item)

        assert item.phase == BootstrapPhase.PREPARE_BUILD
        assert "matches constraint" in caplog.text


class TestPhasePrepareBuild:
    """Tests for _phase_prepare_build: dep installation and extraction."""

    def test_installs_system_deps_and_returns_backend_sdist_items(
        self, tmp_context: WorkContext
    ) -> None:
        """Installs build system deps, extracts backend/sdist deps, returns all."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        system_deps = {Requirement("setuptools")}
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps=system_deps,
        )

        backend_item = _make_resolve_item(req="wheel")
        sdist_item = _make_resolve_item(req="flit-core")

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={Requirement("wheel")},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value={Requirement("flit-core")},
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[backend_item], [sdist_item]],
            ),
        ):
            result = bt._phase_prepare_build(item)

        assert item.phase == BootstrapPhase.BUILD
        assert item.build_backend_deps == {Requirement("wheel")}
        assert item.build_sdist_deps == {Requirement("flit-core")}
        mock_env.install.assert_called_once_with(system_deps)
        assert result == [item, backend_item, sdist_item]

    def test_no_extra_deps_returns_item_only(self, tmp_context: WorkContext) -> None:
        """When backend and sdist deps are empty, returns only the item."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        system_deps = {Requirement("setuptools")}
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps=system_deps,
        )

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value=set(),
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value=set(),
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[], []],
            ),
        ):
            result = bt._phase_prepare_build(item)

        assert result == [item]
        assert item.phase == BootstrapPhase.BUILD
        mock_env.install.assert_called_once_with(system_deps)

    def test_install_called_once_with_system_deps(
        self, tmp_context: WorkContext
    ) -> None:
        """build_env.install is called exactly once with build_system_deps."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        system_deps = {Requirement("setuptools"), Requirement("wheel")}
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps=system_deps,
        )

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={Requirement("cython")},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value=set(),
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[], []],
            ),
        ):
            bt._phase_prepare_build(item)

        mock_env.install.assert_called_once_with(system_deps)

    def test_creates_items_with_correct_requirement_types(
        self, tmp_context: WorkContext
    ) -> None:
        """Backend deps tagged BUILD_BACKEND, sdist deps tagged BUILD_SDIST."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
        )

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={Requirement("wheel")},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value={Requirement("flit-core")},
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[], []],
            ) as mock_create_items,
        ):
            bt._phase_prepare_build(item)

        calls = mock_create_items.call_args_list
        assert calls[0] == call(
            {Requirement("wheel")},
            RequirementType.BUILD_BACKEND,
            item.req,
            item.resolved_version,
        )
        assert calls[1] == call(
            {Requirement("flit-core")},
            RequirementType.BUILD_SDIST,
            item.req,
            item.resolved_version,
        )


class TestPhaseBuild:
    """Tests for _phase_build: conditional dep install and result construction."""

    def _make_build_phase_item(self, tmp_context: WorkContext) -> WorkItem:
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        sdist_root.parent.mkdir(parents=True, exist_ok=True)
        return _make_build_item(
            phase=BootstrapPhase.BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
            build_backend_deps={Requirement("wheel")},
            build_sdist_deps={Requirement("flit-core")},
        )

    def test_disjoint_deps_installs_remaining(self, tmp_context: WorkContext) -> None:
        """Disjoint backend/sdist deps from system deps triggers install."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        sdist_root.parent.mkdir(parents=True, exist_ok=True)
        item = _make_build_item(
            phase=BootstrapPhase.BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
            build_backend_deps={Requirement("wheel")},
            build_sdist_deps={Requirement("flit-core")},
        )
        mock_wheel = tmp_context.work_dir / "testpkg-1.0-py3-none-any.whl"

        with (
            patch.object(bt, "_do_build", return_value=(mock_wheel, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            result = bt._phase_build(item)

        mock_env.install.assert_called_once_with(
            {Requirement("wheel"), Requirement("flit-core")}
        )
        assert item.phase == BootstrapPhase.PROCESS_INSTALL_DEPS
        assert len(result) == 1

    def test_overlapping_deps_skips_install(self, tmp_context: WorkContext) -> None:
        """Overlapping backend/sdist deps with system deps skips install."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        sdist_root.parent.mkdir(parents=True, exist_ok=True)
        item = _make_build_item(
            phase=BootstrapPhase.BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
            build_backend_deps={Requirement("setuptools")},
            build_sdist_deps=set(),
        )

        with (
            patch.object(bt, "_do_build", return_value=(None, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            bt._phase_build(item)

        mock_env.install.assert_not_called()

    def test_partial_overlap_deps_skips_install(self, tmp_context: WorkContext) -> None:
        """isdisjoint is False on partial overlap, so install is skipped entirely
        even for deps not in build_system_deps (here: cython).
        """
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        sdist_root.parent.mkdir(parents=True, exist_ok=True)
        item = _make_build_item(
            phase=BootstrapPhase.BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
            build_backend_deps={Requirement("setuptools"), Requirement("cython")},
            build_sdist_deps=set(),
        )

        with (
            patch.object(bt, "_do_build", return_value=(None, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            bt._phase_build(item)

        mock_env.install.assert_not_called()

    def test_do_build_receives_item_fields(self, tmp_context: WorkContext) -> None:
        """build_sdist_only and cached_wheel_filename are forwarded to _do_build."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        sdist_root.parent.mkdir(parents=True, exist_ok=True)
        cached_wheel = tmp_context.work_dir / "cached.whl"
        item = _make_build_item(
            phase=BootstrapPhase.BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_sdist_only=True,
            cached_wheel_filename=cached_wheel,
        )

        with (
            patch.object(bt, "_do_build", return_value=(None, None)) as mock_do_build,
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            bt._phase_build(item)

        mock_do_build.assert_called_once_with(
            req=item.req,
            resolved_version=item.resolved_version,
            sdist_root_dir=sdist_root,
            build_env=mock_env,
            build_sdist_only=True,
            cached_wheel_filename=cached_wheel,
        )

    def test_build_result_references_item_build_env(
        self, tmp_context: WorkContext
    ) -> None:
        """build_result.build_env is the same object as item.build_env."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_build_phase_item(tmp_context)

        with (
            patch.object(bt, "_do_build", return_value=(None, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            result = bt._phase_build(item)

        assert result[0].build_result is not None
        assert result[0].build_result.build_env is item.build_env

    def test_build_result_uses_source_type_from_sources(
        self, tmp_context: WorkContext
    ) -> None:
        """source_type comes from sources.get_source_type, not hardcoded."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_build_phase_item(tmp_context)

        with (
            patch.object(bt, "_do_build", return_value=(None, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.PREBUILT),
        ):
            bt._phase_build(item)

        assert item.build_result is not None
        assert item.build_result.source_type == SourceType.PREBUILT

    def test_returns_single_item_at_process_install_deps(
        self, tmp_context: WorkContext
    ) -> None:
        """_phase_build returns exactly [item] with phase PROCESS_INSTALL_DEPS."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_build_phase_item(tmp_context)

        with (
            patch.object(bt, "_do_build", return_value=(None, None)),
            patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        ):
            result = bt._phase_build(item)

        assert len(result) == 1
        assert result[0] is item
        assert item.phase == BootstrapPhase.PROCESS_INSTALL_DEPS


class TestPhaseProcessInstallDeps:
    """Tests for _phase_process_install_deps: hooks, dep extraction, error modes."""

    def _make_process_item(self, tmp_context: WorkContext) -> WorkItem:
        build_result = SourceBuildResult(
            wheel_filename=tmp_context.work_dir / "testpkg-1.0-py3-none-any.whl",
            sdist_filename=tmp_context.work_dir / "testpkg-1.0.tar.gz",
            unpack_dir=tmp_context.work_dir / "testpkg-1.0",
            sdist_root_dir=tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0",
            build_env=Mock(),
            source_type=SourceType.SDIST,
        )
        return _make_build_item(
            phase=BootstrapPhase.PROCESS_INSTALL_DEPS,
            build_result=build_result,
            source_url="https://pkg.test/testpkg-1.0.tar.gz",
        )

    def test_normal_path_returns_item_and_dep_items(
        self, tmp_context: WorkContext
    ) -> None:
        """Normal path: hooks, deps, build order, returns [item, *dep_items]."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_process_item(tmp_context)
        dep_item = _make_resolve_item(req="dep-a")

        with (
            patch("fromager.hooks.run_post_bootstrap_hooks"),
            patch.object(
                bt,
                "_get_install_dependencies",
                return_value=[Requirement("dep-a")],
            ),
            patch.object(
                tmp_context,
                "package_build_info",
                return_value=Mock(pre_built=False),
            ),
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_add_to_build_order") as mock_build_order,
            patch.object(
                bt, "_create_unresolved_work_items", return_value=[dep_item]
            ) as mock_create_items,
        ):
            result = bt._phase_process_install_deps(item)

        assert item.phase == BootstrapPhase.COMPLETE
        assert result == [item, dep_item]
        mock_build_order.assert_called_once()
        mock_create_items.assert_called_once_with(
            [Requirement("dep-a")],
            RequirementType.INSTALL,
            item.req,
            item.resolved_version,
        )

    def test_hook_error_test_mode_records_and_continues(
        self, tmp_context: WorkContext
    ) -> None:
        """Hook error in test mode records failure, dep extraction still runs."""
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = self._make_process_item(tmp_context)

        with (
            patch(
                "fromager.hooks.run_post_bootstrap_hooks",
                side_effect=RuntimeError("hook failed"),
            ),
            patch.object(
                bt, "_get_install_dependencies", return_value=[]
            ) as mock_get_deps,
            patch.object(
                tmp_context,
                "package_build_info",
                return_value=Mock(pre_built=False),
            ),
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_add_to_build_order") as mock_build_order,
            patch.object(bt, "_create_unresolved_work_items", return_value=[]),
        ):
            result = bt._phase_process_install_deps(item)

        assert item.phase == BootstrapPhase.COMPLETE
        assert result == [item]
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "hook"
        mock_get_deps.assert_called_once()
        mock_build_order.assert_called_once()

    def test_hook_error_normal_mode_raises(self, tmp_context: WorkContext) -> None:
        """Hook error in normal mode propagates the exception."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_process_item(tmp_context)

        with (
            patch(
                "fromager.hooks.run_post_bootstrap_hooks",
                side_effect=RuntimeError("hook failed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="hook failed"):
                bt._phase_process_install_deps(item)

    def test_dep_extraction_error_test_mode_uses_empty_deps(
        self, tmp_context: WorkContext
    ) -> None:
        """Dep extraction error in test mode uses empty dep list, still writes build order."""
        bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)
        item = self._make_process_item(tmp_context)

        with (
            patch("fromager.hooks.run_post_bootstrap_hooks"),
            patch.object(
                bt,
                "_get_install_dependencies",
                side_effect=RuntimeError("dep failed"),
            ),
            patch.object(
                tmp_context,
                "package_build_info",
                return_value=Mock(pre_built=False),
            ),
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_add_to_build_order") as mock_build_order,
            patch.object(
                bt, "_create_unresolved_work_items", return_value=[]
            ) as mock_create_items,
        ):
            result = bt._phase_process_install_deps(item)

        assert item.phase == BootstrapPhase.COMPLETE
        assert result == [item]
        assert len(bt.failed_packages) == 1
        assert bt.failed_packages[0]["failure_type"] == "dependency_extraction"
        mock_build_order.assert_called_once()
        mock_create_items.assert_called_once_with(
            [],
            RequirementType.INSTALL,
            item.req,
            item.resolved_version,
        )

    def test_dep_extraction_error_normal_mode_raises(
        self, tmp_context: WorkContext
    ) -> None:
        """Dep extraction error in normal mode propagates the exception."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_process_item(tmp_context)

        with (
            patch("fromager.hooks.run_post_bootstrap_hooks"),
            patch.object(
                bt,
                "_get_install_dependencies",
                side_effect=RuntimeError("dep failed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="dep failed"):
                bt._phase_process_install_deps(item)

    def test_no_install_deps_returns_item_only(self, tmp_context: WorkContext) -> None:
        """When no install deps, returns [item] at COMPLETE phase."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_process_item(tmp_context)

        with (
            patch("fromager.hooks.run_post_bootstrap_hooks"),
            patch.object(bt, "_get_install_dependencies", return_value=[]),
            patch.object(
                tmp_context,
                "package_build_info",
                return_value=Mock(pre_built=False),
            ),
            patch.object(tmp_context.constraints, "get_constraint", return_value=None),
            patch.object(bt, "_add_to_build_order"),
            patch.object(bt, "_create_unresolved_work_items", return_value=[]),
        ):
            result = bt._phase_process_install_deps(item)

        assert result == [item]
        assert item.phase == BootstrapPhase.COMPLETE

    def test_build_order_called_with_correct_args(
        self, tmp_context: WorkContext
    ) -> None:
        """_add_to_build_order receives correct source_type, prebuilt, constraint."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = self._make_process_item(tmp_context)
        constraint = Requirement("testpkg>=1.0")

        with (
            patch("fromager.hooks.run_post_bootstrap_hooks"),
            patch.object(bt, "_get_install_dependencies", return_value=[]),
            patch.object(
                tmp_context,
                "package_build_info",
                return_value=Mock(pre_built=True),
            ),
            patch.object(
                tmp_context.constraints,
                "get_constraint",
                return_value=constraint,
            ),
            patch.object(bt, "_add_to_build_order") as mock_build_order,
            patch.object(bt, "_create_unresolved_work_items", return_value=[]),
        ):
            bt._phase_process_install_deps(item)

        mock_build_order.assert_called_once_with(
            req=item.req,
            version=item.resolved_version,
            source_url=item.source_url,
            source_type=SourceType.SDIST,
            prebuilt=True,
            constraint=constraint,
        )


class TestFilterDepsSatisfiedByBuildSystem:
    """Tests for build-backend/sdist dep filtering against build-system deps."""

    def _setup_graph_with_build_system_dep(
        self,
        ctx: WorkContext,
        parent_name: str,
        parent_version: str,
        dep_name: str,
        dep_version: str,
        download_url: str = "https://pypi.test/simple/",
    ) -> None:
        """Add a parent node and a BUILD_SYSTEM edge to the dependency graph."""
        ctx.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(f"{parent_name}=={parent_version}"),
            req_version=Version(parent_version),
            download_url=download_url,
        )
        ctx.dependency_graph.add_dependency(
            parent_name=canonicalize_name(parent_name),
            parent_version=Version(parent_version),
            req_type=RequirementType.BUILD_SYSTEM,
            req=Requirement(f"{dep_name}=={dep_version}"),
            req_version=Version(dep_version),
            download_url=download_url,
        )

    def test_satisfied_dep_reuses_build_system_version(
        self, tmp_context: WorkContext
    ) -> None:
        """A build-backend dep with no pin reuses the build-system version."""
        self._setup_graph_with_build_system_dep(
            tmp_context, "biotite", "1.6.0", "hatch-cython", "0.5.0"
        )
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("hatch-cython"): (
                Version("0.5.0"),
                "https://pypi.test/simple/",
            )
        }
        parent = (Requirement("biotite==1.6.0"), Version("1.6.0"))

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {Requirement("hatch-cython")},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == set()
        mock_add.assert_called_once_with(
            req=Requirement("hatch-cython"),
            req_type=RequirementType.BUILD_BACKEND,
            req_version=Version("0.5.0"),
            download_url="https://pypi.test/simple/",
            parent=parent,
        )

    def test_satisfied_dep_with_compatible_specifier(
        self, tmp_context: WorkContext
    ) -> None:
        """A build-backend dep with a compatible specifier reuses build-system version."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.5.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {Requirement("foo>=1.0")},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == set()
        mock_add.assert_called_once()

    def test_unsatisfied_dep_passes_through(self, tmp_context: WorkContext) -> None:
        """A dep not in build-system is returned for independent resolution."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))
        wheel_req = Requirement("wheel")

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {wheel_req},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == {wheel_req}
        mock_add.assert_not_called()

    def test_incompatible_specifier_passes_through(
        self, tmp_context: WorkContext
    ) -> None:
        """A dep whose specifier conflicts with build-system version is not filtered."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))
        foo_req = Requirement("foo>=2.0")

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {foo_req},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == {foo_req}
        mock_add.assert_not_called()

    def test_incompatible_specifier_logs_warning(
        self, tmp_context: WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A conflicting dep logs a warning about the build config conflict."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))

        with patch.object(bt, "_add_to_graph"):
            bt._filter_deps_satisfied_by_build_system(
                {Requirement("foo>=2.0")},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert "conflicts with" in caplog.text
        assert "foo>=2.0" in caplog.text
        assert "foo==1.0" in caplog.text

    def test_mixed_satisfied_and_unsatisfied(self, tmp_context: WorkContext) -> None:
        """Only unsatisfied deps are returned; satisfied deps get graph edges."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("hatch-cython"): (
                Version("0.5.0"),
                "https://pypi.test/simple/",
            )
        }
        parent = (Requirement("biotite==1.6.0"), Version("1.6.0"))
        cython_req = Requirement("hatch-cython")
        wheel_req = Requirement("wheel")

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {cython_req, wheel_req},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == {wheel_req}
        mock_add.assert_called_once()

    def test_empty_deps_returns_empty(self, tmp_context: WorkContext) -> None:
        """Empty deps set returns empty set."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))

        result = bt._filter_deps_satisfied_by_build_system(
            set(),
            resolved_build_sys,
            RequirementType.BUILD_BACKEND,
            parent,
        )

        assert result == set()

    def test_empty_build_system_returns_all_deps(
        self, tmp_context: WorkContext
    ) -> None:
        """When no build-system deps exist, all deps pass through."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        wheel_req = Requirement("wheel")
        parent = (Requirement("testpkg==1.0"), Version("1.0"))

        result = bt._filter_deps_satisfied_by_build_system(
            {wheel_req},
            {},
            RequirementType.BUILD_BACKEND,
            parent,
        )

        assert result == {wheel_req}

    def test_dep_with_extras_passes_through(self, tmp_context: WorkContext) -> None:
        """A dep with extras is not filtered even if the name matches."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        resolved_build_sys = {
            canonicalize_name("foo"): (Version("1.0"), "https://pypi.test/simple/")
        }
        parent = (Requirement("testpkg==1.0"), Version("1.0"))
        extras_req = Requirement("foo[bar]>=1.0")

        with patch.object(bt, "_add_to_graph") as mock_add:
            result = bt._filter_deps_satisfied_by_build_system(
                {extras_req},
                resolved_build_sys,
                RequirementType.BUILD_BACKEND,
                parent,
            )

        assert result == {extras_req}
        mock_add.assert_not_called()


class TestGetResolvedBuildSystemVersions:
    """Tests for _get_resolved_build_system_versions."""

    def test_returns_build_system_edges(self, tmp_context: WorkContext) -> None:
        """Returns resolved versions from BUILD_SYSTEM edges."""
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement("biotite==1.6.0"),
            req_version=Version("1.6.0"),
            download_url="https://pypi.test/simple/",
        )
        tmp_context.dependency_graph.add_dependency(
            parent_name=canonicalize_name("biotite"),
            parent_version=Version("1.6.0"),
            req_type=RequirementType.BUILD_SYSTEM,
            req=Requirement("hatch-cython==0.5"),
            req_version=Version("0.5.0"),
            download_url="https://pypi.test/hatch-cython/",
        )
        tmp_context.dependency_graph.add_dependency(
            parent_name=canonicalize_name("biotite"),
            parent_version=Version("1.6.0"),
            req_type=RequirementType.INSTALL,
            req=Requirement("numpy"),
            req_version=Version("2.0.0"),
            download_url="https://pypi.test/numpy/",
        )

        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(req="biotite", version="1.6.0")

        result = bt._get_resolved_build_system_versions(item)

        assert canonicalize_name("hatch-cython") in result
        assert result[canonicalize_name("hatch-cython")] == (
            Version("0.5.0"),
            "https://pypi.test/hatch-cython/",
        )
        assert canonicalize_name("numpy") not in result

    def test_returns_empty_when_parent_not_in_graph(
        self, tmp_context: WorkContext
    ) -> None:
        """Returns empty dict when parent node is not in the graph."""
        bt = bootstrapper.Bootstrapper(tmp_context)
        item = _make_build_item(req="nonexistent", version="1.0")

        result = bt._get_resolved_build_system_versions(item)

        assert result == {}


class TestPhasePrepareBuildFiltering:
    """Tests for _phase_prepare_build with build-system satisfaction filtering."""

    def test_satisfied_backend_dep_skips_resolve(
        self, tmp_context: WorkContext
    ) -> None:
        """Backend dep satisfied by build-system is not sent to RESOLVE."""
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement("biotite==1.6.0"),
            req_version=Version("1.6.0"),
            download_url="https://pypi.test/simple/",
        )
        tmp_context.dependency_graph.add_dependency(
            parent_name=canonicalize_name("biotite"),
            parent_version=Version("1.6.0"),
            req_type=RequirementType.BUILD_SYSTEM,
            req=Requirement("hatch-cython==0.5"),
            req_version=Version("0.5.0"),
            download_url="https://pypi.test/simple/",
        )

        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "biotite-1.6.0" / "biotite-1.6.0"
        item = _make_build_item(
            req="biotite",
            version="1.6.0",
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("hatch-cython==0.5")},
        )

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={Requirement("hatch-cython")},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value=set(),
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                return_value=[],
            ) as mock_create,
        ):
            result = bt._phase_prepare_build(item)

        assert item.phase == BootstrapPhase.BUILD
        calls = mock_create.call_args_list
        assert calls[0][0][0] == set()
        assert calls[1][0][0] == set()
        assert item.build_backend_deps == set()
        assert result == [item]

    def test_extras_dep_not_filtered(self, tmp_context: WorkContext) -> None:
        """Backend dep with extras passes through even if name matches."""
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement("testpkg==1.0"),
            req_version=Version("1.0"),
            download_url="https://pypi.test/simple/",
        )
        tmp_context.dependency_graph.add_dependency(
            parent_name=canonicalize_name("testpkg"),
            parent_version=Version("1.0"),
            req_type=RequirementType.BUILD_SYSTEM,
            req=Requirement("foo==1.0"),
            req_version=Version("1.0"),
            download_url="https://pypi.test/simple/",
        )

        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        extras_req = Requirement("foo[bar]>=1.0")
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("foo==1.0")},
        )

        resolve_item = _make_resolve_item(req="foo")

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={extras_req},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value=set(),
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[resolve_item], []],
            ) as mock_create,
        ):
            result = bt._phase_prepare_build(item)

        calls = mock_create.call_args_list
        assert calls[0][0][0] == {extras_req}
        assert item.build_backend_deps == {extras_req}
        assert result == [item, resolve_item]

    def test_unsatisfied_backend_dep_creates_resolve_item(
        self, tmp_context: WorkContext
    ) -> None:
        """Backend dep NOT in build-system is sent to RESOLVE normally."""
        tmp_context.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement("testpkg==1.0"),
            req_version=Version("1.0"),
            download_url="https://pypi.test/simple/",
        )

        bt = bootstrapper.Bootstrapper(tmp_context)
        mock_env = Mock()
        sdist_root = tmp_context.work_dir / "testpkg-1.0" / "testpkg-1.0"
        item = _make_build_item(
            phase=BootstrapPhase.PREPARE_BUILD,
            build_env=mock_env,
            sdist_root_dir=sdist_root,
            build_system_deps={Requirement("setuptools")},
        )

        resolve_item = _make_resolve_item(req="wheel")

        with (
            patch(
                "fromager.dependencies.get_build_backend_dependencies",
                return_value={Requirement("wheel")},
            ),
            patch(
                "fromager.dependencies.get_build_sdist_dependencies",
                return_value=set(),
            ),
            patch.object(
                bt,
                "_create_unresolved_work_items",
                side_effect=[[resolve_item], []],
            ) as mock_create,
        ):
            result = bt._phase_prepare_build(item)

        calls = mock_create.call_args_list
        assert calls[0][0][0] == {Requirement("wheel")}
        assert result == [item, resolve_item]
