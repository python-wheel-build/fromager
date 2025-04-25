import os
import pathlib
import shlex
import subprocess
import sys
import typing
from io import TextIOWrapper

from .log import get_logger

logger = get_logger(__name__)

HERE = pathlib.Path(__file__).absolute().parent

NETWORK_ISOLATION: list[str] | None
if sys.platform == "linux":
    # runner script with `unshare -rn` + `ip link set lo up`
    NETWORK_ISOLATION = [str(HERE / "run_network_isolation.sh")]
else:
    NETWORK_ISOLATION = None


def network_isolation_cmd() -> typing.Sequence[str]:
    """Detect network isolation wrapper

    Raises ValueError when network isolation is not supported
    Returns: command list to run a process with network isolation
    """
    if NETWORK_ISOLATION:
        return NETWORK_ISOLATION
    raise ValueError(f"unsupported platform {sys.platform}")


def detect_network_isolation() -> None:
    """Detect if network isolation is available and working

    unshare needs 'unshare' and 'clone' syscall. Docker's seccomp policy
    blocks these syscalls. Podman's policy allows them.
    """
    cmd = network_isolation_cmd()
    if os.name == "posix":
        check = [*cmd, "true"]
        subprocess.check_call(check, stderr=subprocess.STDOUT)


class NetworkIsolationError(subprocess.CalledProcessError):
    pass


# based on pyproject_hooks/_impl.py: quiet_subprocess_runner
def run(
    cmd: typing.Sequence[str],
    *,
    cwd: str | None = None,
    extra_environ: dict[str, typing.Any] | None = None,
    network_isolation: bool = False,
    log_filename: str | None = None,
    stdin: TextIOWrapper | None = None,
) -> str:
    """Call the subprocess while logging output"""
    if extra_environ is None:
        extra_environ = {}
    env = os.environ.copy()
    env.update(extra_environ)

    if network_isolation:
        # prevent network access by creating a new network namespace that
        # has no routing configured.
        cmd = [
            *network_isolation_cmd(),
            *cmd,
        ]

    logger.debug(
        "running: %s %s in %s",
        " ".join(f"{k}={shlex.quote(v)}" for k, v in extra_environ.items()),
        " ".join(shlex.quote(str(s)) for s in cmd),
        cwd or ".",
    )
    if log_filename:
        with open(log_filename, "w") as log_file:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=stdin,
            )
        with open(log_filename, "r", encoding="utf-8") as f:
            output = f.read()
    else:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=stdin,
        )
        output = completed.stdout.decode("utf-8") if completed.stdout else ""
    if completed.returncode != 0:
        logger.error("%s failed with %s", cmd, output)
        err_type = subprocess.CalledProcessError
        if network_isolation:
            # Look for a few common messages that mean there is a network
            # isolation problem and change the exception type to make it easier
            # for the caller to recognize that case.
            for substr in [
                "connection refused",
                "network unreachable",
                "Network is unreachable",
            ]:
                if substr in output:
                    err_type = NetworkIsolationError
        raise err_type(completed.returncode, cmd, output)
    logger.debug("output: %s", output)
    return output
