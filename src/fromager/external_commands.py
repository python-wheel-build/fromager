import logging
import os
import shlex
import subprocess
import sys
import typing
from io import TextIOWrapper

unshare_network: typing.Callable[[], None] | None
if sys.platform == "linux":
    from ._unshare_linux import unshare_network
else:
    unshare_network = None

logger = logging.getLogger(__name__)


def detect_network_isolation() -> None:
    """Detect if network isolation is available and working

    unshare syscall needs 'unshare' and 'clone' syscall. Docker's seccomp
    policy blocks these syscalls. Podman's policy allows them.
    """
    if unshare_network is not None:
        subprocess.check_call(
            ["true"], stderr=subprocess.STDOUT, preexec_fn=unshare_network
        )
    else:
        raise ValueError(f"unsupported platform {sys.platform}")


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

    preexec_fn: typing.Callable[[], None] | None
    if network_isolation:
        if unshare_network is None:
            raise ValueError(
                "network isolation requested but 'unshare_network' is not available"
            )
        preexec_fn = unshare_network
    else:
        preexec_fn = None

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
                preexec_fn=preexec_fn,
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
            preexec_fn=preexec_fn,
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
                "network unreachable",
                "Network is unreachable",
                "connection refused",  # DNS server 127.0.0.53:53 unreachable
            ]:
                if substr in output:
                    err_type = NetworkIsolationError
        raise err_type(completed.returncode, cmd, output)
    logger.debug("output: %s", output)
    return output
