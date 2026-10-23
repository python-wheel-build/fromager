import json
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
    packagesettings,
    server,
    sources,
    wheels,
)
from ..log import requirement_ctxvar

logger = logging.getLogger(__name__)


@click.group()
def step() -> None:
    "Step-by-step commands"
    pass


@step.command()
@click.option(
    "--output-format",
    type=click.Choice(["path", "json"]),
    default="path",
    show_default=True,
    help="Print the path or a JSON object with path and artifact kind.",
)
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.argument("sdist_server_url")
@click.pass_obj
def download_source_archive(
    wkctx: context.WorkContext,
    output_format: str,
    dist_name: str,
    dist_version: Version,
    sdist_server_url: str,
) -> None:
    """download source for one version of one package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    token = requirement_ctxvar.set(req)
    source_url, version = sources.resolve_source(
        ctx=wkctx, req=req, sdist_server_url=sdist_server_url
    )
    downloaded_source = sources.download_source(
        ctx=wkctx,
        req=req,
        version=version,
        download_url=source_url,
    )
    requirement_ctxvar.reset(token)
    if output_format == "json":
        print(
            json.dumps(
                {
                    "path": str(downloaded_source.path),
                    "kind": downloaded_source.kind.value,
                }
            )
        )
    else:
        print(downloaded_source.path)


@step.command()
@click.option(
    "--source-kind",
    type=click.Choice(
        [
            packagesettings.DownloadKind.sdist.value,
            packagesettings.DownloadKind.tarball.value,
            packagesettings.DownloadKind.git_checkout.value,
        ]
    ),
    default=packagesettings.DownloadKind.sdist.value,
    show_default=True,
    help="Kind returned by the source download step.",
)
@click.option(
    "--source-path",
    type=click.Path(exists=True, path_type=pathlib.Path),
    help="Downloaded source path; Git checkouts must use the standard work directory layout.",
)
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def prepare_source(
    wkctx: context.WorkContext,
    source_kind: str,
    source_path: pathlib.Path | None,
    dist_name: str,
    dist_version: Version,
) -> None:
    """ensure the source code is in a form ready for building a wheel

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    req = Requirement(f"{dist_name}=={dist_version}")
    token = requirement_ctxvar.set(req)
    download_kind = packagesettings.DownloadKind(source_kind)
    sdists_downloads = pathlib.Path(wkctx.sdists_repo) / "downloads"
    checkout = (
        wkctx.work_dir / f"{req.name}-{dist_version}" / f"{req.name}-{dist_version}"
    )
    source_filename: pathlib.Path | None
    if source_path is not None:
        source_filename = source_path
    elif download_kind is packagesettings.DownloadKind.git_checkout:
        source_filename = checkout if checkout.is_dir() else None
    else:
        source_filename = finders.find_sdist(
            wkctx, wkctx.sdists_downloads, req, str(dist_version)
        )
    if source_filename is None:
        if download_kind is packagesettings.DownloadKind.git_checkout:
            raise RuntimeError(f"Cannot find Git checkout for {req} at {checkout}")
        dir_contents: list[str] = []
        for ext in ["*.tar.gz", "*.zip"]:
            dir_contents.extend(str(e) for e in wkctx.sdists_downloads.glob(ext))
        raise RuntimeError(
            f"Cannot find source for {req.name} version {dist_version} in {sdists_downloads} among {dir_contents}"
        )
    source_root_dir = sources.prepare_source(
        ctx=wkctx,
        req=req,
        source_filename=source_filename,
        version=dist_version,
        download_kind=download_kind,
    )
    requirement_ctxvar.reset(token)
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
    token = requirement_ctxvar.set(req)
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    build_env = build_environment.BuildEnvironment(
        ctx=wkctx,
        req=req,
        sdist_root_dir=source_root_dir,
    )
    sdist_filename = sources.build_sdist(
        ctx=wkctx,
        req=req,
        version=dist_version,
        sdist_root_dir=source_root_dir,
        build_env=build_env,
    )
    requirement_ctxvar.reset(token)
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
@click.option(
    "--wheel-server-url",
    default="",
    type=str,
    help="URL for the wheel server for builds",
)
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def prepare_build(
    wkctx: context.WorkContext,
    wheel_server_url: str,
    dist_name: str,
    dist_version: Version,
) -> None:
    """set up build environment to build the package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    wkctx.wheel_server_url = wheel_server_url
    server.start_wheel_server(wkctx)
    req = Requirement(f"{dist_name}=={dist_version}")
    token = requirement_ctxvar.set(req)
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    build_environment.prepare_build_environment(
        ctx=wkctx,
        req=req,
        version=dist_version,
        sdist_root_dir=source_root_dir,
    )
    requirement_ctxvar.reset(token)


@step.command()
@click.option(
    "--wheel-server-url",
    default="",
    type=str,
    help="URL for the wheel server for builds",
)
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.pass_obj
def build_wheel(
    wkctx: context.WorkContext,
    wheel_server_url: str,
    dist_name: str,
    dist_version: Version,
) -> None:
    """build a wheel from prepared source

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    wkctx.wheel_server_url = wheel_server_url
    req = Requirement(f"{dist_name}=={dist_version}")
    token = requirement_ctxvar.set(req)
    source_root_dir = _find_source_root_dir(wkctx, wkctx.work_dir, req, dist_version)
    server.start_wheel_server(wkctx)
    build_env = build_environment.BuildEnvironment(
        ctx=wkctx,
        req=req,
        sdist_root_dir=source_root_dir,
    )
    wheel_filename = wheels.build_wheel(
        ctx=wkctx,
        req=req,
        sdist_root_dir=source_root_dir,
        version=dist_version,
        build_env=build_env,
    )
    requirement_ctxvar.reset(token)
    print(wheel_filename)
