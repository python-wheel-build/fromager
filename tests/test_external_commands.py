import logging
import os
import pathlib
import subprocess
import typing
from unittest import mock

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import external_commands, log, packagesettings


def test_external_commands_environ() -> None:
    env = {"BLAH": "test"}
    output = external_commands.run(["sh", "-c", "echo $BLAH"], extra_environ=env)
    assert "test\n" == output


def test_external_commands_log_file(tmp_path: pathlib.Path) -> None:
    log_filename = pathlib.Path(tmp_path) / "test.log"
    env = {"BLAH": "test"}
    output = external_commands.run(
        ["sh", "-c", "echo $BLAH"],
        extra_environ=env,
        log_filename=str(log_filename),
    )
    assert "test\n" == output
    assert log_filename.exists()
    file_contents = log_filename.read_text()
    assert "test\n" == file_contents


@mock.patch(
    "subprocess.run",
    return_value=mock.Mock(returncode=0, stdout=b"test output\n"),
)
@mock.patch(
    "fromager.external_commands.network_isolation_cmd",
    return_value=["/bin/unshare", "--net", "--map-current-user"],
)
@mock.patch.dict(os.environ)
def test_external_commands_network_isolation(
    m_network_isolation_cmd: mock.Mock,
    m_run: mock.Mock,
) -> None:
    os.environ.clear()
    external_commands.run(
        ["host", "github.com"],
        extra_environ={},
        network_isolation=True,
    )
    m_network_isolation_cmd.assert_called()
    m_run.assert_called_with(
        [
            "/bin/unshare",
            "--net",
            "--map-current-user",
            "host",
            "github.com",
        ],
        cwd=None,
        env={},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=None,
    )


NETWORK_ISOLATION_ERROR: Exception | None = None
try:
    external_commands.detect_network_isolation()
except Exception as err:
    NETWORK_ISOLATION_ERROR = err
    SUPPORTS_NETWORK_ISOLATION: bool = False
else:
    SUPPORTS_NETWORK_ISOLATION = True


@pytest.mark.skipif(
    not SUPPORTS_NETWORK_ISOLATION,
    reason=f"network isolation is not supported: {NETWORK_ISOLATION_ERROR}",
)
def test_external_commands_network_isolation_real() -> None:
    with pytest.raises(external_commands.NetworkIsolationError) as e:
        external_commands.run(
            ["host", "github.com"],
            network_isolation=True,
            extra_environ={"LC_ALL": "C"},
        )
    exc = typing.cast(subprocess.CalledProcessError, e.value)
    assert exc.returncode == 1


def test_external_command_output_prefix(caplog: pytest.LogCaptureFixture) -> None:
    """Test that external command output is prefixed with package name on each line."""
    # Set up the log record factory to enable automatic prefixing
    old_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(log.FromagerLogRecord)

    try:
        req = Requirement("test-package==1.0.0")
        version = Version("1.0.0")

        with log.req_ctxvar_context(req, version):
            with caplog.at_level(logging.DEBUG, logger="fromager.external_commands"):
                # Run a command that produces multi-line output
                # Use printf for cross-platform compatibility (echo -e doesn't work on macOS)
                external_commands.run(["printf", "line1\\nline2\\nline3"])

            # Get the last debug log record (the output message)
            output_rec = caplog.records[-1]
            message = output_rec.getMessage()

            # Verify that each line has the package name prefix
            # The first line gets the prefix from FromagerLogRecord.getMessage()
            # Continuation lines get it from external_commands.run()
            expected_prefix = "test-package-1.0.0: "
            assert message.startswith(expected_prefix), (
                f"Message should start with '{expected_prefix}'"
            )

            # Check that all lines have the prefix
            lines = message.split("\n")
            for line in lines:
                if line:  # Skip empty lines
                    assert line.startswith(expected_prefix), (
                        f"Line '{line}' should start with '{expected_prefix}'"
                    )
    finally:
        # Restore the original log record factory
        logging.setLogRecordFactory(old_factory)


def test_external_commands_error_includes_package_name(caplog: typing.Any) -> None:
    """Test that package name is included in error logs when context var is set"""
    logging.setLogRecordFactory(log.FromagerLogRecord)

    req = Requirement("test-package==1.0.0")
    version = Version("1.0.0")

    with log.req_ctxvar_context(req, version):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                external_commands.run(["sh", "-c", "exit 1"])

    error_logs = [
        record.message for record in caplog.records if record.levelname == "ERROR"
    ]
    assert len(error_logs) > 0
    assert any("test-package-1.0.0:" in msg for msg in error_logs), (
        f"Expected package name in error logs, got: {error_logs}"
    )


def test_format_exception_formats_chained_exceptions() -> None:
    """Test that _format_exception formats chained exceptions correctly"""
    from fromager import __main__

    # Test basic exception formatting
    exception_without_cause = subprocess.CalledProcessError(
        1, ["command"], output="some output"
    )
    message = __main__._format_exception(exception_without_cause)
    assert "Command '['command']' returned non-zero exit status 1" in message

    # Test chained exception formatting with "because"
    try:
        try:
            raise ValueError("Root cause")
        except ValueError as e:
            raise RuntimeError("Higher level error") from e
    except RuntimeError as chained_exc:
        formatted = __main__._format_exception(chained_exc)
        assert "Higher level error" in formatted
        assert "because" in formatted
        assert "Root cause" in formatted


# --- env_filter wiring tests ---


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b""))
@mock.patch.dict(os.environ, {"HOME": "/h", "SECRET": "s"}, clear=True)
def test_run_env_filter_none_passes_full_environ(m_run: mock.Mock) -> None:
    """Without env_filter, the full os.environ is passed to the subprocess."""
    external_commands.run(["true"])
    call_env = m_run.call_args.kwargs["env"]
    assert call_env["HOME"] == "/h"
    assert call_env["SECRET"] == "s"


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b""))
@mock.patch.dict(os.environ, {"HOME": "/h", "SECRET": "s"}, clear=True)
def test_run_env_filter_strips_deleted_vars(m_run: mock.Mock) -> None:
    """With env_filter configured, deleted vars are stripped from the env."""
    env_filter = packagesettings.ExternalCommands(delete_env=["*"])
    external_commands.run(["true"], env_filter=env_filter)
    call_env = m_run.call_args.kwargs["env"]
    assert call_env["HOME"] == "/h"
    assert "SECRET" not in call_env


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b""))
@mock.patch.dict(os.environ, {"HOME": "/h", "SECRET": "s"}, clear=True)
def test_run_env_filter_extra_environ_survives(m_run: mock.Mock) -> None:
    """extra_environ values are applied after filtering and never stripped."""
    env_filter = packagesettings.ExternalCommands(delete_env=["*"])
    external_commands.run(
        ["true"],
        extra_environ={"MY_BUILD_VAR": "42"},
        env_filter=env_filter,
    )
    call_env = m_run.call_args.kwargs["env"]
    assert call_env["MY_BUILD_VAR"] == "42"
    assert "SECRET" not in call_env


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b""))
@mock.patch.dict(os.environ, {"HOME": "/h", "CI_TOKEN": "t", "USER": "u"}, clear=True)
def test_run_env_filter_selective_delete(m_run: mock.Mock) -> None:
    """Selective delete_env removes only matching vars."""
    env_filter = packagesettings.ExternalCommands(delete_env=["CI_TOKEN"])
    external_commands.run(["true"], env_filter=env_filter)
    call_env = m_run.call_args.kwargs["env"]
    assert call_env["HOME"] == "/h"
    assert call_env["USER"] == "u"
    assert "CI_TOKEN" not in call_env


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b""))
@mock.patch.dict(os.environ, {"HOME": "/h", "SECRET": "s"}, clear=True)
def test_run_env_filter_default_is_noop(m_run: mock.Mock) -> None:
    """Default ExternalCommands (empty lists) passes all POSIX-valid vars."""
    env_filter = packagesettings.ExternalCommands()
    external_commands.run(["true"], env_filter=env_filter)
    call_env = m_run.call_args.kwargs["env"]
    assert call_env["HOME"] == "/h"
    assert call_env["SECRET"] == "s"
