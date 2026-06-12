import contextlib
import os
import pathlib
import sys
import typing

import click
from packaging.version import Version

from . import requirements_file


@contextlib.contextmanager
def output_file_or_stdout(
    path: pathlib.Path | None,
) -> typing.Generator[typing.TextIO, None, None]:
    """Context manager that opens *path* for writing or yields stdout.

    When *path* is ``None``, yields :data:`sys.stdout` (never closed).
    Otherwise opens the file, yields it, and closes on exit.
    """
    if path:
        fh = open(path, "w")
        try:
            yield fh
        finally:
            fh.close()
    else:
        yield sys.stdout


class ClickPath(click.Path):
    """ClickPath that returns pathlib.Path"""

    def convert(
        self,
        value: str | os.PathLike[str],
        param: click.core.Parameter | None,
        ctx: click.core.Context | None,
    ) -> pathlib.Path:
        path = super().convert(value=value, param=param, ctx=ctx)
        if isinstance(path, bytes):
            return pathlib.Path(os.fsdecode(path))
        return pathlib.Path(path)


class PackageVersion(click.ParamType):
    """Package version type that returns a packaging version"""

    name = "package_version"

    def convert(
        self,
        value: str,
        param: click.core.Parameter | None,
        ctx: click.core.Context | None,
    ) -> Version:
        try:
            return Version(value)
        except Exception as e:
            self.fail(
                f"Invalid package version '{value}' ({e})",
                param,
                ctx,
            )


class RequirementType(click.ParamType):
    """RequirementType that returns a requirement type"""

    name = "requirement_type"

    def convert(
        self,
        value: str,
        param: click.core.Parameter | None,
        ctx: click.core.Context | None,
    ) -> requirements_file.RequirementType:
        try:
            return requirements_file.RequirementType(value)
        except Exception:
            self.fail(
                f"Invalid requirement type '{value}', allowed values are {[r.value for r in requirements_file.RequirementType]}",
                param,
                ctx,
            )
