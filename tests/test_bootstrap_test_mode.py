"""Tests for --test-mode feature (Phase 1: Basic functionality).

Tests the essential test mode functionality:
- Bootstrapper initialization with test_mode flag
- Exception handling: catch errors, log, continue
- Bootstrapper.finalize() exit codes
"""

import pathlib
import tempfile
import typing
from unittest.mock import Mock

import pytest

from fromager import bootstrapper, context


@pytest.fixture
def mock_context() -> typing.Generator[context.WorkContext, None, None]:
    """Create a mock WorkContext for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = pathlib.Path(tmpdir)

        mock_ctx = Mock(spec=context.WorkContext)
        mock_ctx.work_dir = work_dir
        mock_ctx.wheels_build = work_dir / "wheels-build"
        mock_ctx.wheels_downloads = work_dir / "wheels-downloads"
        mock_ctx.wheels_prebuilt = work_dir / "wheels-prebuilt"
        mock_ctx.sdists_builds = work_dir / "sdists-builds"
        mock_ctx.wheel_server_url = None
        mock_ctx.constraints = Mock()
        mock_ctx.constraints.get_constraint = Mock(return_value=None)
        mock_ctx.settings = Mock()
        mock_ctx.variant = "test"

        for d in [
            mock_ctx.wheels_build,
            mock_ctx.wheels_downloads,
            mock_ctx.wheels_prebuilt,
            mock_ctx.sdists_builds,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        yield mock_ctx


class TestBootstrapperInitialization:
    """Test Bootstrapper initialization with test_mode parameter."""

    def test_test_mode_enabled(self, mock_context: context.WorkContext) -> None:
        """Test Bootstrapper with test_mode=True."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context, test_mode=True)
        assert bt.test_mode is True
        assert isinstance(bt.failed_packages, list)
        assert len(bt.failed_packages) == 0

    def test_test_mode_disabled_by_default(
        self, mock_context: context.WorkContext
    ) -> None:
        """Test Bootstrapper with test_mode=False (default)."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context)
        assert bt.test_mode is False

    def test_test_mode_incompatible_with_sdist_only(
        self, mock_context: context.WorkContext
    ) -> None:
        """Test that test_mode and sdist_only are mutually exclusive."""
        with pytest.raises(ValueError, match="--test-mode requires full wheel builds"):
            bootstrapper.Bootstrapper(ctx=mock_context, test_mode=True, sdist_only=True)


class TestFinalizeExitCodes:
    """Test finalize() returns correct exit codes."""

    def test_finalize_no_failures_returns_zero(
        self, mock_context: context.WorkContext
    ) -> None:
        """Test finalize returns 0 when no failures in test mode."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context, test_mode=True)
        assert bt.finalize() == 0

    def test_finalize_with_failures_returns_one(
        self, mock_context: context.WorkContext
    ) -> None:
        """Test finalize returns 1 when there are failures in test mode."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context, test_mode=True)
        bt.failed_packages.append("failing-pkg")
        assert bt.finalize() == 1

    def test_finalize_not_in_test_mode_returns_zero(
        self, mock_context: context.WorkContext
    ) -> None:
        """Test finalize returns 0 when not in test mode (regardless of failures)."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context, test_mode=False)
        # Even if we manually add failures (shouldn't happen), it returns 0
        bt.failed_packages.append("some-pkg")
        assert bt.finalize() == 0

    def test_finalize_logs_failed_packages(
        self, mock_context: context.WorkContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test finalize logs the list of failed packages."""
        bt = bootstrapper.Bootstrapper(ctx=mock_context, test_mode=True)
        bt.failed_packages.extend(["pkg-a", "pkg-b", "pkg-c"])

        exit_code = bt.finalize()

        assert exit_code == 1
        assert "3 package(s) failed" in caplog.text
        assert "pkg-a" in caplog.text
        assert "pkg-b" in caplog.text
        assert "pkg-c" in caplog.text
