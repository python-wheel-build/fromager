import logging
import pathlib

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, sources, build_environment

logger = logging.getLogger(__name__)


def update_extra_environ(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version | None,
    sdist_root_dir: pathlib.Path,
    extra_environ: dict[str, str],
    build_env: build_environment.BuildEnvironment,
) -> None:
    """Update extra_environ in-place"""
    logger.info("update_extra_environ resolved_version=%s", version)
    marker = ctx.work_dir / "update_extra_environ.txt"
    with marker.open(encoding="utf-8", mode="a") as f:
        f.write(f"{version}\n")
    return None


def build_sdist(
    ctx: context.WorkContext,
    extra_environ: dict,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_env: build_environment.BuildEnvironment,
) -> pathlib.Path:
    return sources.pep517_build_sdist(
        ctx=ctx,
        extra_environ=extra_environ,
        req=req,
        sdist_root_dir=sdist_root_dir,
        version=version,
        build_env=build_env,
    )
