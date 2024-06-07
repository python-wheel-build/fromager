import logging

import click
from packaging.requirements import Requirement

from .. import sdist, server, sources, wheels

logger = logging.getLogger(__name__)


@click.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.argument('sdist_server_url')
@click.pass_obj
def build(wkctx, dist_name, dist_version, sdist_server_url):
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

    req = Requirement(f'{dist_name}=={dist_version}')

    # Download
    logger.info('downloading source archive for %s from %s', req, sdist_server_url)
    source_filename, version, source_url, _ = sources.download_source(
        wkctx, req, [sdist_server_url],
    )
    logger.debug('saved %s version %s from %s to %s',
                 req.name, version, source_url, source_filename)

    # Prepare source
    logger.info('preparing source directory for %s', req)
    source_root_dir = sources.prepare_source(wkctx, req, source_filename, dist_version)

    # Build environment
    logger.info('preparing build environment for %s', req)
    sdist.prepare_build_environment(wkctx, req, source_root_dir)

    logger.info('building for %s', req)
    build_env = wheels.BuildEnvironment(wkctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(wkctx, req, source_root_dir, build_env)

    print(wheel_filename)
