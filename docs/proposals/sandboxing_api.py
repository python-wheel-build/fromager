import os
import pathlib
import subprocess
import typing
from collections.abc import Mapping, Sequence

from packaging.requirements import Requirement

from fromager import context

type _OptionalFile = int | typing.IO[typing.Any] | None
type _StrOrBytesPath = str | bytes | os.PathLike[str] | os.PathLike[bytes]


class SandboxLifecycle(typing.Protocol):
    """Sandbox setup or teardown hook.

    Used for ``setup_sandbox`` (runs after ``prepare_source``) and
    ``teardown_sandbox`` (always runs via ``finally``). Plain functions
    with a matching signature satisfy this protocol.
    """

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
    ) -> None: ...


class RunCommand(typing.Protocol):
    """Run an external command, returning `subprocess.CompletedProcess`.

    Used for ``run_sandboxed`` (confined execution) and
    ``run_unconfined`` (unconfined, with optional monitoring).
    Accepts a subset of `subprocess.run` keyword arguments.
    Returns `CompletedProcess` even when ``returncode`` is non-zero.
    """

    def __call__(
        self,
        args: Sequence[_StrOrBytesPath],
        *,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        stdin: _OptionalFile = None,
        stdout: _OptionalFile = None,
        stderr: _OptionalFile = None,
        cwd: _StrOrBytesPath | None = None,
        timeout: float | None = None,
        text: bool | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]: ...


class ExternalCommands(typing.Protocol):
    """Sandboxing hooks, configured under ``external_commands``.

    The sandbox is set up and torn down per package+version build.
    """

    setup_sandbox: SandboxLifecycle
    """Runs after the ``prepare_source`` hook."""

    teardown_sandbox: SandboxLifecycle
    """Runs in ``finally``, regardless of build outcome."""

    run_sandboxed: RunCommand
    """Run a command inside the sandbox."""

    run_unconfined: RunCommand
    """Run a command outside the sandbox."""
