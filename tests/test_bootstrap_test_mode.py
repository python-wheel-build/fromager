"""Tests for bootstrap --test-mode functionality.

Tests for test mode failure tracking and BuildResult.
"""

from unittest import mock

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import bootstrapper
from fromager.context import WorkContext


class MockBuildError(Exception):
    """Mock exception for simulating build failures."""

    pass


def test_test_mode_tracks_complete_failures(tmp_context: WorkContext) -> None:
    """Test that test mode tracks failures with full context when both build and fallback fail."""
    bt = bootstrapper.Bootstrapper(tmp_context, test_mode=True)

    # Mock to always fail
    def mock_build_wheel_and_sdist(req, version, pbi, build_sdist_only):
        raise MockBuildError(f"Build failed for {req.name}")

    with mock.patch.object(
        bt, "_build_wheel_and_sdist", side_effect=mock_build_wheel_and_sdist
    ):
        req = Requirement("broken-package==1.0")
        version = Version("1.0")
        pbi = tmp_context.package_build_info(req)

        result = bt._build_package(req, version, pbi, build_sdist_only=False)

        # Verify complete failure is tracked with full context
        assert result.failed
        assert result.req == req
        assert result.resolved_version == version
        assert result.exception_type == "MockBuildError"
        assert result.exception_message is not None
        assert "Build failed for broken-package" in result.exception_message

        # Verify failure is in failed_builds list
        assert len(bt.failed_builds) == 1
        failed_build = bt.failed_builds[0]
        assert failed_build.req is not None
        assert failed_build.req.name == "broken-package"


def test_normal_mode_still_fails_fast(tmp_context: WorkContext) -> None:
    """Test that normal mode (test_mode=False) still raises exceptions immediately."""
    bt = bootstrapper.Bootstrapper(tmp_context, test_mode=False)

    def mock_build_wheel_and_sdist(req, version, pbi, build_sdist_only):
        raise MockBuildError(f"Build failed for {req.name}")

    with mock.patch.object(
        bt, "_build_wheel_and_sdist", side_effect=mock_build_wheel_and_sdist
    ):
        req = Requirement("failing-package==1.0")
        version = Version("1.0")
        pbi = tmp_context.package_build_info(req)

        # Should raise immediately in normal mode
        with pytest.raises(MockBuildError, match="Build failed for failing-package"):
            bt._build_package(req, version, pbi, build_sdist_only=False)


def test_build_result_captures_exception_context() -> None:
    """Test that BuildResult.failure() properly captures exception context."""
    req = Requirement("test-package>=1.0")
    version = Version("1.2.3")
    exception = ValueError("Something went wrong")

    result = bootstrapper.BuildResult.failure(
        req=req, resolved_version=version, exception=exception
    )

    # Verify all context is captured
    assert result.failed
    assert result.req == req
    assert result.resolved_version == version
    assert result.exception is exception
    assert result.exception_type == "ValueError"
    assert result.exception_message == "Something went wrong"
    assert result.wheel_filename is None
    assert result.sdist_filename is None
