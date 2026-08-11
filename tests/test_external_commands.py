import logging
import os
import pathlib
import subprocess
import typing
from unittest import mock

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import external_commands, log


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


def test_format_exception_deduplicates_embedded_cause_suffix() -> None:
    """Regression test for #1243.

    resolver.py wraps failures as ``f"...: {original_msg}"`` where
    ``original_msg`` is ``str(err)`` before chaining ``from err`` - the
    cause's raw message ends up embedded at the *end* of the outer
    message. Without deduping, ``_format_exception`` prints it twice via
    "... because ...".
    """
    from resolvelib.resolvers import ResolverException

    from fromager import __main__

    try:
        try:
            raise ResolverException("found no match")
        except ResolverException as err:
            original_msg = str(err)
            raise ResolverException(
                f"Unable to resolve requirement: {original_msg}"
            ) from err
    except ResolverException as err:
        formatted = __main__._format_exception(err)

    assert formatted == "Unable to resolve requirement: found no match"


def test_format_exception_still_shows_because_for_unrelated_cause() -> None:
    """Unrelated causes (not embedded in the outer message) are still

    joined with "because", so the dedupe check doesn't over-suppress.
    """
    from fromager import __main__

    try:
        try:
            raise ValueError("Root cause")
        except ValueError as e:
            raise RuntimeError("Higher level error") from e
    except RuntimeError as chained:
        assert (
            __main__._format_exception(chained)
            == "Higher level error because Root cause"
        )


def test_format_exception_preserves_nested_cause_after_dedup() -> None:
    """Deduping the immediate embedded cause must not drop a deeper cause.

    If the outer message ends with the immediate cause's raw text, that
    part is deduped - but the immediate cause may itself have its own
    cause with information not present anywhere in the outer message,
    which must still be shown.
    """
    from fromager import __main__

    try:
        try:
            raise ValueError("root cause")
        except ValueError as root:
            raise RuntimeError("middle error") from root
    except RuntimeError as middle:
        try:
            raise RuntimeError(f"outer error: {middle}") from middle
        except RuntimeError as outer:
            formatted = __main__._format_exception(outer)

    assert formatted == "outer error: middle error because root cause"


def test_format_exception_does_not_dedupe_coincidental_suffix() -> None:
    """A short cause message that coincidentally matches the tail of an

    unrelated outer message must not be deduped - only the resolver.py
    ``f"...: {original_msg}"`` construction (anchored on the ": "
    separator) should trigger dedup.
    """
    from fromager import __main__

    try:
        raise ValueError("match")
    except ValueError as cause:
        try:
            raise RuntimeError("failed to match") from cause
        except RuntimeError as outer:
            formatted = __main__._format_exception(outer)

    assert formatted == "failed to match because match"
