import logging
import os
import shlex
import shutil
import subprocess
import sys
import typing

logger = logging.getLogger(__name__)

NETWORK_ISOLATION: list[str] | None
if sys.platform == "linux":
    NETWORK_ISOLATION = ["unshare", "--net", "--map-current-user"]
else:
    NETWORK_ISOLATION = None


def network_isolation_cmd() -> tuple[str, ...]:
    """Detect network isolation wrapper

    Raises ValueError when network isolation is not supported
    Returns: command list to run a process with network isolation
    """
    if sys.platform == "linux":
        unshare = shutil.which("unshare")
        if unshare is not None:
            return [unshare, "--net", "--map-current-user"]
        raise ValueError("Linux system without 'unshare' command")
    raise ValueError(f"unsupported platform {sys.platform}")


def detect_network_isolation():
    """Detect if network isolation is available and working

    unshare needs 'unshare' and 'clone' syscall. Docker's seccomp policy
    blocks these syscalls. Podman's policy allows them.
    """
    cmd = network_isolation_cmd()
    if os.name == "posix":
        subprocess.check_call(cmd + ["true"], stderr=subprocess.STDOUT)


# based on pyproject_hooks/_impl.py: quiet_subprocess_runner
def run(
    cmd: typing.Sequence[str],
    *,
    cwd: str | None = None,
    extra_environ: dict[str, typing.Any] | None = None,
    network_isolation: bool = False,
    log_filename: str | None = None,
) -> str:
    """Call the subprocess while logging output"""
    if extra_environ is None:
        extra_environ = {}
    env = os.environ.copy()
    env.update(extra_environ)

    if network_isolation:
        # prevent network access by creating a new network namespace that
        # has no routing configured.
        cmd = network_isolation_cmd() + cmd

    logger.debug(
        "running: %s %s in %s",
        " ".join(f"{k}={v}" for k, v in extra_environ.items()),
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
        )
        output = completed.stdout.decode("utf-8") if completed.stdout else ""
    if completed.returncode != 0:
        logger.error("%s failed with %s", cmd, output)
        raise subprocess.CalledProcessError(completed.returncode, cmd, output)
    logger.debug("output: %s", output)
    return output
