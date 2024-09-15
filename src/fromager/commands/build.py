import json
import logging
import pathlib
from urllib.parse import urlparse

import click
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from fromager import (
    build_environment,
    clickext,
    context,
    hooks,
    progress,
    server,
    sources,
    wheels,
)

logger = logging.getLogger(__name__)


@click.command()
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.argument("sdist_server_url")
@click.pass_obj
def build(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
    sdist_server_url: str,
) -> None:
    """Build a single version of a single wheel

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    1. Downloads the source distribution.

    2. Unpacks it and prepares the source via patching, vendoring rust
       dependencies, etc.

    3. Prepares a build environment with the build dependencies.

    4. Builds the wheel.

    Refer to the 'step' commands for scripting these stages
    separately.

    """
    server.start_wheel_server(wkctx)
    req = Requirement(f"{dist_name}=={dist_version}")
    source_url, version = sources.resolve_source(
        ctx=wkctx, req=req, sdist_server_url=sdist_server_url
    )
    wheel_filename = _build(wkctx, version, req, source_url)
    print(wheel_filename)


@click.command()
@click.argument("build_order_file")
@click.option(
    "--skip-existing",
    default=False,
    is_flag=True,
)
@click.pass_obj
def build_sequence(
    wkctx: context.WorkContext,
    build_order_file: str,
    skip_existing: bool,
) -> None:
    """Build a sequence of wheels in order

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'build' command for each item in
    the build order file.

    """
    server.start_wheel_server(wkctx)
    if skip_existing:
        logger.info(
            "skipping builds for versions of packages available at %s",
            wkctx.wheel_server_url,
        )

    logger.info("reading build order from %s", build_order_file)
    with open(build_order_file, "r") as f:
        for entry in progress.progress(json.load(f)):
            dist_name = entry["dist"]
            resolved_version = Version(entry["version"])
            source_download_url = entry["source_url"]
            req = Requirement(f"{dist_name}=={resolved_version}")

            if skip_existing and _is_wheel_built(wkctx, dist_name, resolved_version):
                logger.info(
                    "%s: skipping building wheels for %s==%s since it already exists",
                    dist_name,
                    dist_name,
                    resolved_version,
                )
                continue

            if entry["prebuilt"]:
                logger.info(
                    "%s: downloading prebuilt wheel %s==%s",
                    dist_name,
                    dist_name,
                    resolved_version,
                )
                wheel_filename = wheels.download_wheel(
                    req, source_download_url, wkctx.wheels_build
                )
            else:
                logger.info(
                    "%s: building %s==%s", dist_name, dist_name, resolved_version
                )
                wheel_filename = _build(
                    wkctx, resolved_version, req, source_download_url
                )

            server.update_wheel_mirror(wkctx)
            # After we update the wheel mirror, the built file has
            # moved to a new directory.
            wheel_filename = wkctx.wheels_downloads / wheel_filename.name
            print(wheel_filename)


def _build(
    wkctx: context.WorkContext,
    resolved_version: Version,
    req: Requirement,
    source_download_url: str,
) -> pathlib.Path:
    source_filename = sources.download_source(
        ctx=wkctx,
        req=req,
        version=resolved_version,
        download_url=source_download_url,
    )
    logger.debug(
        "%s: saved sdist of version %s from %s to %s",
        req.name,
        resolved_version,
        source_download_url,
        source_filename,
    )

    # Prepare source
    source_root_dir = sources.prepare_source(
        wkctx, req, source_filename, resolved_version
    )

    # Build environment
    build_environment.prepare_build_environment(wkctx, req, source_root_dir)
    build_env = build_environment.BuildEnvironment(wkctx, source_root_dir.parent, None)

    # Make a new source distribution, in case we patched the code.
    sdist_filename = sources.build_sdist(
        ctx=wkctx,
        req=req,
        version=resolved_version,
        sdist_root_dir=source_root_dir,
        build_env=build_env,
    )

    # Build
    wheel_filename = wheels.build_wheel(
        ctx=wkctx,
        req=req,
        sdist_root_dir=source_root_dir,
        version=resolved_version,
        build_env=build_env,
    )

    hooks.run_post_build_hooks(
        ctx=wkctx,
        req=req,
        dist_name=canonicalize_name(req.name),
        dist_version=str(resolved_version),
        sdist_filename=sdist_filename,
        wheel_filename=wheel_filename,
    )

    return wheel_filename


def _is_wheel_built(
    wkctx: context.WorkContext, dist_name: str, resolved_version: Version
) -> bool:
    req = Requirement(f"{dist_name}=={resolved_version}")

    try:
        logger.info(f"{req.name}: checking if {req} was already built")
        url, _ = wheels.resolve_prebuilt_wheel(wkctx, req, [wkctx.wheel_server_url])
        pbi = wkctx.package_build_info(req)
        build_tag_from_settings = pbi.build_tag(resolved_version)
        build_tag = build_tag_from_settings if build_tag_from_settings else (0, "")
        wheel_filename = urlparse(url).path.rsplit("/", 1)[-1]
        _, _, build_tag_from_name, _ = parse_wheel_filename(wheel_filename)
        existing_build_tag = build_tag_from_name if build_tag_from_name else (0, "")
        if (
            existing_build_tag[0] > build_tag[0]
            and existing_build_tag[1] == build_tag[1]
        ):
            raise ValueError(
                f"{dist_name}: changelog for version {resolved_version} is inconsistent. Found build tag {existing_build_tag} but expected {build_tag}"
            )
        return existing_build_tag == build_tag
    except Exception:
        logger.info(f"{req.name}: could not locate prebuilt wheel. Will build {req}")
        return False
