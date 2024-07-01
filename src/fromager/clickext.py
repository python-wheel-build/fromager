import os
import pathlib

import click
from packaging.version import Version


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
