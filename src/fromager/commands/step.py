import logging
import pathlib

import click
from packaging.requirements import Requirement
from packaging.version import Version

from .. import (
    build_environment,
    clickext,
    context,
    finders,
    server,
    sources,
    wheels,
)

logger = logging.getLogger(__name__)


@click.group()
def step() -> None:
    "Step-by-step commands"
    pass


@step.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.argument("sdist_server_url")
@click.pass_obj
def download_source_archive(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
    sdist_server_url: str,
) -> None:
    """download the source code archive for one version of one package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    source_url, version = sources.resolve_source(
        ctx=wkctx, req=req, sdist_server_url=sdist_server_url
    )
    filename = sources.download_source(
        ctx=wkctx,
        req=req,
        version=version,
        download_url=source_url,
    )
    print(filename)


@step.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def prepare_source(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
) -> None:
    """ensure the source code is in a form ready for building a wheel

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    sdists_downloads = pathlib.Path(wkctx.sdists_repo) / "downloads"
    source_filename = finders.find_sdist(
        wkctx, wkctx.sdists_downloads, req, str(dist_version)
    )
    if source_filename is None:
        dir_contents: list[str] = []
        for ext in ["*.tar.gz", "*.zip"]:
            dir_contents.extend(str(e) for e in wkctx.sdists_downloads.glob(ext))
        raise RuntimeError(
            f"Cannot find sdist for {req.name} version {dist_version} in {sdists_downloads} among {dir_contents}"
        )
    # FIXME: Does the version need to be a Version instead of str?
    source_root_dir = sources.prepare_source(wkctx, req, source_filename, dist_version)
    print(source_root_dir)


@step.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def build_sdist(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
) -> None:
    """build a new source distribution for the package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    The source distribution is placed in the `sdists-repo/builds`
    directory.

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    build_env = build_environment.BuildEnvironment(wkctx, source_root_dir.parent, None)
    sdist_filename = sources.build_sdist(
        ctx=wkctx,
        req=req,
        version=dist_version,
        sdist_root_dir=source_root_dir,
        build_env=build_env,
    )
    print(sdist_filename)


def _find_source_root_dir(
    wkctx: context.WorkContext,
    work_dir: pathlib.Path,
    req: Requirement,
    dist_version: Version,
) -> pathlib.Path:
    source_root_dir = finders.find_source_dir(wkctx, work_dir, req, str(dist_version))
    if source_root_dir:
        return source_root_dir
    work_dir_contents = list(str(e) for e in work_dir.glob("*"))
    raise RuntimeError(
        f"Cannot find source directory for {req.name} version {dist_version} among {work_dir_contents}"
    )


@step.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def prepare_build(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
) -> None:
    """set up build environment to build the package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    server.start_wheel_server(wkctx)
    req = Requirement(f"{dist_name}=={dist_version}")
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    build_environment.prepare_build_environment(wkctx, req, source_root_dir)


@step.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def build_wheel(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
) -> None:
    """build a wheel from prepared source

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    build_env = build_environment.BuildEnvironment(wkctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(
        ctx=wkctx,
        req=req,
        sdist_root_dir=source_root_dir,
        version=dist_version,
        build_env=build_env,
    )
    print(wheel_filename)
