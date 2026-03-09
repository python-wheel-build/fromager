"""Hook functions for extra environment variable management."""

from __future__ import annotations

import pathlib
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from .. import overrides

if typing.TYPE_CHECKING:
    from .. import build_environment, context


def default_update_extra_environ(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version | None,
    sdist_root_dir: pathlib.Path,
    extra_environ: dict[str, str],
    build_env: build_environment.BuildEnvironment,
) -> None:
    """Update extra_environ in-place"""
    return None


def get_extra_environ(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version | None,
    sdist_root_dir: pathlib.Path,
    build_env: build_environment.BuildEnvironment,
) -> dict[str, str]:
    """Get extra environment variables from settings and update hook"""
    pbi = ctx.package_build_info(req)
    extra_environ = pbi.get_extra_environ(
        build_env=build_env,
        version=version,
    )
    overrides.find_and_invoke(
        req.name,
        "update_extra_environ",
        default_update_extra_environ,
        ctx=ctx,
        req=req,
        version=version,
        sdist_root_dir=sdist_root_dir,
        extra_environ=extra_environ,
        build_env=build_env,
    )
    return extra_environ
