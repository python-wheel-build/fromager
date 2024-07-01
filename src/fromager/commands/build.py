import json
import logging
import pathlib

import click
from packaging.requirements import Requirement
from packaging.version import Version

from .. import clickext, context, sdist, server, sources, wheels

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
):
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
    wheel_filename = _build(wkctx, dist_name, dist_version, sdist_server_url)
    print(wheel_filename)


@click.command()
@click.argument("build_order_file")
@click.argument("sdist_server_url")
@click.pass_obj
def build_sequence(
    wkctx: context.WorkContext,
    build_order_file: str,
    sdist_server_url: str,
):
    """Build a sequence of wheels in order

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'build' command for each item in
    the build order file.

    """
    with open(build_order_file, "r") as f:
        for entry in json.load(f):
            wheel_filename = _build(
                wkctx, entry["dist"], entry["version"], sdist_server_url
            )
            server.update_wheel_mirror(wkctx)
            # After we update the wheel mirror, the built file has
            # moved to a new directory.
            wheel_filename = wkctx.wheels_downloads / wheel_filename.name
            print(wheel_filename)


def _build(
    wkctx: context.WorkContext,
    dist_name: str,
    dist_version: Version,
    sdist_server_url: str,
) -> pathlib.Path:
    server.start_wheel_server(wkctx)

    req = Requirement(f"{dist_name}=={dist_version}")

    # Download
    source_filename, version, source_url, _ = sources.download_source(
        wkctx,
        req,
        [sdist_server_url],
    )
    logger.debug(
        "saved %s version %s from %s to %s",
        req.name,
        version,
        source_url,
        source_filename,
    )

    # Prepare source
    source_root_dir = sources.prepare_source(wkctx, req, source_filename, dist_version)

    # Build environment
    sdist.prepare_build_environment(wkctx, req, source_root_dir)

    # Make a new source distribution, in case we patched the code.
    sources.build_sdist(wkctx, req, source_root_dir)

    # Build
    build_env = wheels.BuildEnvironment(wkctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(wkctx, req, source_root_dir, build_env)
    return wheel_filename
