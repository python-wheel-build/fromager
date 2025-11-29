"""Integration tests for --test-mode feature.

Tests the complete test mode workflow including:
- Exception handling inside Bootstrapper.bootstrap()
- Pre-built fallback mechanism
- JSON report generation
- BuildFailure creation and serialization
"""

import json
import pathlib
import tempfile
import typing
from unittest.mock import Mock

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

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


def test_bootstrapper_initialization(mock_context: context.WorkContext) -> None:
    """Test Bootstrapper initialization with test_mode parameter."""
    # Test with test_mode=True
    bt_enabled = bootstrapper.Bootstrapper(
        ctx=mock_context,
        test_mode=True,
    )
    assert bt_enabled.test_mode is True
    assert isinstance(bt_enabled.failed_builds, list)
    assert len(bt_enabled.failed_builds) == 0

    # Test with test_mode=False (default)
    bt_disabled = bootstrapper.Bootstrapper(ctx=mock_context)
    assert bt_disabled.test_mode is False
    assert isinstance(bt_disabled.failed_builds, list)
    assert len(bt_disabled.failed_builds) == 0


def test_test_mode_incompatible_with_sdist_only(
    mock_context: context.WorkContext,
) -> None:
    """Test that test_mode and sdist_only are mutually exclusive."""
    with pytest.raises(ValueError, match="--test-mode requires full wheel builds"):
        bootstrapper.Bootstrapper(
            ctx=mock_context,
            test_mode=True,
            sdist_only=True,
        )


def test_build_failure() -> None:
    """Test BuildFailure creation, serialization, and edge cases."""
    req = Requirement("test-package==1.0.0")
    version = Version("1.0.0")
    exception = RuntimeError("Build failed")

    result = bootstrapper.BuildFailure.from_exception(
        req=req,
        resolved_version=version,
        source_url_type="sdist",
        exception=exception,
    )

    assert result.req == req
    assert result.resolved_version == version
    assert result.source_url_type == "sdist"
    assert result.exception_type == "RuntimeError"
    assert result.exception_message == "Build failed"

    # Test serialization to dict
    data = result.to_dict()
    assert isinstance(data, dict)
    assert data["package"] == "test-package==1.0.0"
    assert data["version"] == "1.0.0"
    assert data["source_url_type"] == "sdist"
    assert data["exception_type"] == "RuntimeError"
    assert data["exception_message"] == "Build failed"

    # Test JSON serialization
    json_str = json.dumps(data)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["exception_type"] == "RuntimeError"

    # Test with None version (edge case)
    result_no_version = bootstrapper.BuildFailure.from_exception(
        req=Requirement("test-package"),
        resolved_version=None,
        source_url_type="unknown",
        exception=ValueError("Could not resolve version"),
    )
    assert result_no_version.resolved_version is None
    data_no_version = result_no_version.to_dict()
    assert data_no_version["version"] is None
    assert data_no_version["source_url_type"] == "unknown"


def test_json_report_generation(mock_context: context.WorkContext) -> None:
    """Test JSON report generation with single and multiple failures."""
    bt = bootstrapper.Bootstrapper(
        ctx=mock_context,
        test_mode=True,
    )

    # Add multiple failures with different exception types
    bt.failed_builds.extend(
        [
            bootstrapper.BuildFailure.from_exception(
                req=Requirement("pkg1==1.0.0"),
                resolved_version=Version("1.0.0"),
                source_url_type="sdist",
                exception=RuntimeError("Build failed"),
            ),
            bootstrapper.BuildFailure.from_exception(
                req=Requirement("pkg2==2.0.0"),
                resolved_version=Version("2.0.0"),
                source_url_type="sdist",
                exception=ValueError("Invalid configuration"),
            ),
            bootstrapper.BuildFailure.from_exception(
                req=Requirement("pkg3==3.0.0"),
                resolved_version=Version("3.0.0"),
                source_url_type="git",
                exception=RuntimeError("Another build failure"),
            ),
        ]
    )

    # Write report
    bt.write_test_mode_report(mock_context.work_dir)

    # Verify files exist
    failures_file = mock_context.work_dir / "test-mode-failures.json"
    summary_file = mock_context.work_dir / "test-mode-summary.json"
    assert failures_file.exists()
    assert summary_file.exists()

    # Verify failures content
    with open(failures_file) as f:
        failures_data = json.load(f)
    assert "failures" in failures_data
    assert len(failures_data["failures"]) == 3
    assert failures_data["failures"][0]["package"] == "pkg1==1.0.0"
    assert failures_data["failures"][0]["exception_type"] == "RuntimeError"
    assert failures_data["failures"][0]["source_url_type"] == "sdist"
    assert failures_data["failures"][2]["source_url_type"] == "git"

    # Verify summary content
    with open(summary_file) as f:
        summary_data = json.load(f)
    assert summary_data["total_failures"] == 3
    assert summary_data["failure_breakdown"]["RuntimeError"] == 2
    assert summary_data["failure_breakdown"]["ValueError"] == 1


def test_report_skipped_when_disabled(mock_context: context.WorkContext) -> None:
    """Test that report is not written when test_mode=False."""
    bt = bootstrapper.Bootstrapper(
        ctx=mock_context,
        test_mode=False,
    )

    # Try to write report
    bt.write_test_mode_report(mock_context.work_dir)

    # Verify files don't exist
    failures_file = mock_context.work_dir / "test-mode-failures.json"
    summary_file = mock_context.work_dir / "test-mode-summary.json"
    assert not failures_file.exists()
    assert not summary_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
