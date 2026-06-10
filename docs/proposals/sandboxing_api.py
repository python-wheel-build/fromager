import os
import pathlib
import subprocess
import typing
from collections.abc import Mapping, Sequence

from packaging.requirements import Requirement

from fromager import context

type _OptionalFile = int | typing.IO[typing.Any] | None
type _StrOrBytesPath = str | bytes | os.PathLike[str] | os.PathLike[bytes]


def setup_sandbox(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> None:
    """Set up sandboxing

    Executed after `prepare_source` hook. Can be used to set up sandbox or chown/chmod the sdist_root_dir.
    """


def teardown_sandbox(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> None:
    """Tear down sandboxing

    Executed when cleaning up the build environment.
    """


def run_sandboxed(
    args: Sequence[_StrOrBytesPath],
    *,
    # Fromager args
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    # subprocess args
    stdin: _OptionalFile = None,
    stdout: _OptionalFile = None,
    stderr: _OptionalFile = None,
    cwd: _StrOrBytesPath | None = None,
    timeout: float | None = None,
    text: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    """Run command in a sandbox"""
    raise NotImplementedError


def run_unconfined(
    args: Sequence[_StrOrBytesPath],
    *,
    # Fromager args
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    # subprocess args
    stdin: _OptionalFile = None,
    stdout: _OptionalFile = None,
    stderr: _OptionalFile = None,
    cwd: _StrOrBytesPath | None = None,
    timeout: float | None = None,
    text: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    """Run command unconfined without a sandbox"""
    raise NotImplementedError
