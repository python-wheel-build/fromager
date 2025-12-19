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

import pytest

from fromager import bootstrapper, context


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
