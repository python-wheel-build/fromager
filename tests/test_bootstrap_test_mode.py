"""Tests for --test-mode feature.

Tests the test mode functionality:
- Bootstrapper initialization with test_mode flag
- Exception handling: catch errors, log, continue
- Bootstrapper.finalize() exit codes
- JSON failure report generation
- failure_type field for categorizing failures
"""

import json
import pathlib
from unittest import mock

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import bootstrapper, context
from fromager.requirements_file import RequirementType


class TestBootstrapperInitialization:
    """Test Bootstrapper initialization with test_mode parameter."""

    def test_test_mode_enabled(self, tmp_context: context.WorkContext) -> None:
        """Test Bootstrapper with test_mode=True."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        assert bt.test_mode is True
        assert isinstance(bt.failed_packages, list)
        assert len(bt.failed_packages) == 0

    def test_test_mode_disabled_by_default(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test Bootstrapper with test_mode=False (default)."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context)
        assert bt.test_mode is False

    def test_test_mode_incompatible_with_sdist_only(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test that test_mode and sdist_only are mutually exclusive."""
        with pytest.raises(ValueError, match="--test-mode requires full wheel builds"):
            bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True, sdist_only=True)


class TestFinalizeExitCodes:
    """Test finalize() returns correct exit codes."""

    def test_finalize_no_failures_returns_zero(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize returns 0 when no failures in test mode."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        assert bt.finalize() == 0

    def test_finalize_with_failures_returns_one(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize returns 1 when there are failures in test mode."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        bt.failed_packages.append(
            {
                "package": "failing-pkg",
                "version": "1.0.0",
                "exception_type": "RuntimeError",
                "exception_message": "Build failed",
                "failure_type": "bootstrap",
            }
        )
        assert bt.finalize() == 1

    def test_finalize_not_in_test_mode_returns_zero(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize returns 0 when not in test mode (regardless of failures)."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=False)
        # Even if we manually add failures (shouldn't happen), it returns 0
        bt.failed_packages.append(
            {
                "package": "some-pkg",
                "version": "1.0.0",
                "exception_type": "RuntimeError",
                "exception_message": "Error",
                "failure_type": "bootstrap",
            }
        )
        assert bt.finalize() == 0

    def test_finalize_logs_failed_packages(
        self, tmp_context: context.WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test finalize logs the list of failed packages."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        bt.failed_packages.extend(
            [
                {
                    "package": "pkg-a",
                    "version": "1.0",
                    "exception_type": "E",
                    "exception_message": "m",
                    "failure_type": "bootstrap",
                },
                {
                    "package": "pkg-b",
                    "version": "2.0",
                    "exception_type": "E",
                    "exception_message": "m",
                    "failure_type": "hook",
                },
                {
                    "package": "pkg-c",
                    "version": "3.0",
                    "exception_type": "E",
                    "exception_message": "m",
                    "failure_type": "dependency_extraction",
                },
            ]
        )

        exit_code = bt.finalize()

        assert exit_code == 1
        assert "3 package(s) failed" in caplog.text
        assert "pkg-a" in caplog.text
        assert "pkg-b" in caplog.text
        assert "pkg-c" in caplog.text


def _find_failure_report(work_dir: pathlib.Path) -> pathlib.Path | None:
    """Find the test-mode-failures-*.json file in work_dir."""
    reports = list(work_dir.glob("test-mode-failures-*.json"))
    return reports[0] if reports else None


class TestJsonFailureReport:
    """Test JSON failure report generation."""

    def test_finalize_writes_json_report(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize writes test-mode-failures-<timestamp>.json with failure details."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        bt.failed_packages.append(
            {
                "package": "failing-pkg",
                "version": "1.0.0",
                "exception_type": "CalledProcessError",
                "exception_message": "Compilation failed",
                "failure_type": "bootstrap",
            }
        )

        bt.finalize()

        report_path = _find_failure_report(tmp_context.work_dir)
        assert report_path is not None
        assert report_path.name.startswith("test-mode-failures-")
        assert report_path.name.endswith(".json")

        with open(report_path) as f:
            report = json.load(f)

        assert "failures" in report
        assert len(report["failures"]) == 1
        assert report["failures"][0]["package"] == "failing-pkg"
        assert report["failures"][0]["version"] == "1.0.0"
        assert report["failures"][0]["exception_type"] == "CalledProcessError"
        assert report["failures"][0]["exception_message"] == "Compilation failed"
        assert report["failures"][0]["failure_type"] == "bootstrap"

    def test_finalize_no_report_when_no_failures(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize does not write report when there are no failures."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)

        bt.finalize()

        report_path = _find_failure_report(tmp_context.work_dir)
        assert report_path is None

    def test_finalize_report_with_null_version(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize handles failures where version is None (resolution failure)."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        bt.failed_packages.append(
            {
                "package": "failed-to-resolve",
                "version": None,
                "exception_type": "ResolutionError",
                "exception_message": "Could not resolve version",
                "failure_type": "resolution",
            }
        )

        bt.finalize()

        report_path = _find_failure_report(tmp_context.work_dir)
        assert report_path is not None
        with open(report_path) as f:
            report = json.load(f)

        assert report["failures"][0]["version"] is None
        assert report["failures"][0]["failure_type"] == "resolution"

    def test_finalize_report_multiple_failure_types(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test finalize correctly reports multiple failures with different types."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        bt.failed_packages.extend(
            [
                {
                    "package": "pkg-a",
                    "version": "1.0.0",
                    "exception_type": "BuildError",
                    "exception_message": "Failed to compile",
                    "failure_type": "bootstrap",
                },
                {
                    "package": "pkg-b",
                    "version": "2.0.0",
                    "exception_type": "HookError",
                    "exception_message": "Validation failed",
                    "failure_type": "hook",
                },
                {
                    "package": "pkg-c",
                    "version": "3.0.0",
                    "exception_type": "MetadataError",
                    "exception_message": "Could not read metadata",
                    "failure_type": "dependency_extraction",
                },
            ]
        )

        bt.finalize()

        report_path = _find_failure_report(tmp_context.work_dir)
        assert report_path is not None
        with open(report_path) as f:
            report = json.load(f)

        assert len(report["failures"]) == 3
        failure_types = [f["failure_type"] for f in report["failures"]]
        assert "bootstrap" in failure_types
        assert "hook" in failure_types
        assert "dependency_extraction" in failure_types


class TestBootstrapExceptionHandling:
    """Test bootstrap() catches and records exceptions in test mode."""

    def test_resolution_failure_recorded_in_test_mode(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test that resolve_version failures are recorded in test mode."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        req = Requirement("nonexistent-package>=1.0")

        # Mock resolve_version to raise an exception
        with mock.patch.object(
            bt, "resolve_version", side_effect=RuntimeError("Version resolution failed")
        ):
            # Should not raise in test mode
            bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # Verify failure was recorded
        assert len(bt.failed_packages) == 1
        failure = bt.failed_packages[0]
        assert failure["package"] == "nonexistent-package"
        assert (
            failure["version"] is None
        )  # No version available for resolution failures
        assert failure["failure_type"] == "resolution"
        assert "Version resolution failed" in failure["exception_message"]

    def test_resolution_failure_raises_in_normal_mode(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test that resolve_version failures raise in normal mode."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=False)
        req = Requirement("nonexistent-package>=1.0")

        # Mock resolve_version to raise an exception
        with mock.patch.object(
            bt, "resolve_version", side_effect=RuntimeError("Version resolution failed")
        ):
            with pytest.raises(RuntimeError, match="Version resolution failed"):
                bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)


class TestPrebuiltFallback:
    """Test prebuilt fallback behavior in test mode when build fails."""

    def test_fallback_succeeds_no_failure_recorded(
        self, tmp_context: context.WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that successful fallback to prebuilt doesn't record a failure."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        req = Requirement("test-package>=1.0")

        with (
            mock.patch.object(
                bt,
                "resolve_version",
                return_value=("https://sdist.url", Version("1.0")),
            ),
            mock.patch.object(bt, "_add_to_graph"),
            mock.patch.object(bt, "_has_been_seen", return_value=False),
            mock.patch.object(bt, "_mark_as_seen"),
            # First call fails (build), second succeeds (fallback with force_prebuilt)
            mock.patch.object(
                bt,
                "_bootstrap_impl",
                side_effect=[RuntimeError("Build failed"), None],
            ),
            mock.patch.object(
                bt,
                "_resolve_prebuilt_with_history",
                return_value=("https://wheel.url", Version("1.0")),
            ),
        ):
            bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # No failure recorded because fallback succeeded
        assert len(bt.failed_packages) == 0
        assert "successfully used pre-built wheel" in caplog.text

    def test_fallback_version_mismatch_logs_warning(
        self, tmp_context: context.WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that version mismatch during fallback logs a warning."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        req = Requirement("test-package>=1.0")

        with (
            mock.patch.object(
                bt,
                "resolve_version",
                return_value=("https://sdist.url", Version("1.0")),
            ),
            mock.patch.object(bt, "_add_to_graph"),
            mock.patch.object(bt, "_has_been_seen", return_value=False),
            mock.patch.object(bt, "_mark_as_seen"),
            mock.patch.object(
                bt,
                "_bootstrap_impl",
                side_effect=[RuntimeError("Build failed"), None],
            ),
            # Fallback resolves to different version
            mock.patch.object(
                bt,
                "_resolve_prebuilt_with_history",
                return_value=("https://wheel.url", Version("1.1")),
            ),
        ):
            bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # No failure recorded because fallback succeeded
        assert len(bt.failed_packages) == 0
        assert "version mismatch" in caplog.text
        assert "requested 1.0" in caplog.text
        assert "fallback 1.1" in caplog.text

    def test_fallback_also_fails_records_original_error(
        self, tmp_context: context.WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that when fallback also fails, original build error is recorded."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        req = Requirement("test-package>=1.0")

        with (
            mock.patch.object(
                bt,
                "resolve_version",
                return_value=("https://sdist.url", Version("1.0")),
            ),
            mock.patch.object(bt, "_add_to_graph"),
            mock.patch.object(bt, "_has_been_seen", return_value=False),
            mock.patch.object(bt, "_mark_as_seen"),
            # Both build and fallback fail
            mock.patch.object(
                bt,
                "_bootstrap_impl",
                side_effect=[
                    RuntimeError("Original build failed"),
                    RuntimeError("Fallback also failed"),
                ],
            ),
            mock.patch.object(
                bt,
                "_resolve_prebuilt_with_history",
                return_value=("https://wheel.url", Version("1.0")),
            ),
        ):
            bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # Failure recorded with ORIGINAL error, not fallback error
        assert len(bt.failed_packages) == 1
        failure = bt.failed_packages[0]
        assert failure["package"] == "test-package"
        assert failure["version"] == "1.0"
        assert failure["failure_type"] == "bootstrap"
        assert "Original build failed" in failure["exception_message"]
        assert "pre-built fallback also failed" in caplog.text

    def test_fallback_resolution_fails_records_original_error(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test that when prebuilt resolution fails, original build error is recorded."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=True)
        req = Requirement("test-package>=1.0")

        with (
            mock.patch.object(
                bt,
                "resolve_version",
                return_value=("https://sdist.url", Version("1.0")),
            ),
            mock.patch.object(bt, "_add_to_graph"),
            mock.patch.object(bt, "_has_been_seen", return_value=False),
            mock.patch.object(bt, "_mark_as_seen"),
            mock.patch.object(
                bt,
                "_bootstrap_impl",
                side_effect=RuntimeError("Original build failed"),
            ),
            # Prebuilt resolution fails
            mock.patch.object(
                bt,
                "_resolve_prebuilt_with_history",
                side_effect=RuntimeError("No prebuilt available"),
            ),
        ):
            bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # Failure recorded with ORIGINAL error
        assert len(bt.failed_packages) == 1
        assert "Original build failed" in bt.failed_packages[0]["exception_message"]

    def test_build_failure_raises_in_normal_mode(
        self, tmp_context: context.WorkContext
    ) -> None:
        """Test that build failures raise immediately in normal mode (no fallback)."""
        bt = bootstrapper.Bootstrapper(ctx=tmp_context, test_mode=False)
        req = Requirement("test-package>=1.0")

        with (
            mock.patch.object(
                bt,
                "resolve_version",
                return_value=("https://sdist.url", Version("1.0")),
            ),
            mock.patch.object(bt, "_add_to_graph"),
            mock.patch.object(bt, "_has_been_seen", return_value=False),
            mock.patch.object(bt, "_mark_as_seen"),
            mock.patch.object(
                bt,
                "_bootstrap_impl",
                side_effect=RuntimeError("Build failed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Build failed"):
                bt.bootstrap(req=req, req_type=RequirementType.TOP_LEVEL)

        # No fallback attempted in normal mode
        assert len(bt.failed_packages) == 0
