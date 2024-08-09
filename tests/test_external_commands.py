import os
import pathlib
import subprocess
import typing
from unittest import mock

import pytest

from fromager import external_commands


def test_external_commands_environ():
    env = {"BLAH": "test"}
    output = external_commands.run(["sh", "-c", "echo $BLAH"], extra_environ=env)
    assert "test\n" == output


def test_external_commands_log_file(tmp_path):
    log_filename = pathlib.Path(tmp_path) / "test.log"
    env = {"BLAH": "test"}
    output = external_commands.run(
        ["sh", "-c", "echo $BLAH"],
        extra_environ=env,
        log_filename=log_filename,
    )
    assert "test\n" == output
    assert log_filename.exists()
    file_contents = log_filename.read_text()
    assert "test\n" == file_contents


@mock.patch("subprocess.run", return_value=mock.Mock(returncode=0))
@mock.patch(
    "fromager.external_commands.network_isolation_cmd",
    return_value=["/bin/unshare", "--net", "--map-current-user"],
)
@mock.patch.dict(os.environ)
def test_external_commands_network_isolation(
    m_network_isolation_cmd: mock.Mock,
    m_run: mock.Mock,
):
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


try:
    external_commands.detect_network_isolation()
except Exception:
    SUPPORTS_NETWORK_ISOLATION: bool = False
else:
    SUPPORTS_NETWORK_ISOLATION = True


@pytest.mark.skipif(
    not SUPPORTS_NETWORK_ISOLATION, reason="network isolation is not supported"
)
def test_external_commands_network_isolation_real():
    with pytest.raises(external_commands.NetworkIsolationError) as e:
        external_commands.run(
            ["host", "github.com"],
            network_isolation=True,
            extra_environ={"LC_ALL": "C"},
        )
    exc = typing.cast(subprocess.CalledProcessError, e.value)
    assert exc.returncode == 1
