import logging
import pathlib

import click
from packaging.requirements import Requirement

from .. import finders, sdist, server, sources, wheels

from . import bootstrap

logger = logging.getLogger(__name__)


@click.group()
def step():
    "Step-by-step commands"
    pass


@step.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.argument('sdist_server_url')
@click.pass_obj
def download_source_archive(wkctx, dist_name, dist_version, sdist_server_url):
    """download the source code archive for one version of one package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    """
    req = Requirement(f'{dist_name}=={dist_version}')
    logger.info('downloading source archive for %s from %s', req, sdist_server_url)
    filename, version, source_url, _ = sources.download_source(wkctx, req, [sdist_server_url])
    logger.debug('saved %s version %s from %s to %s', req.name, version, source_url, filename)
    print(filename)


@step.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.pass_obj
def prepare_source(wkctx, dist_name, dist_version):
    """ensure the source code is in a form ready for building a wheel

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    """
    req = Requirement(f'{dist_name}=={dist_version}')
    logger.info('preparing source directory for %s', req)
    sdists_downloads = pathlib.Path(wkctx.sdists_repo) / 'downloads'
    source_filename = finders.find_sdist(wkctx.sdists_downloads, req, dist_version)
    if source_filename is None:
        dir_contents = []
        for ext in ['*.tar.gz', '*.zip']:
            dir_contents.extend(str(e) for e in wkctx.sdists_downloads.glob(ext))
        raise RuntimeError(
            f'Cannot find sdist for {req.name} version {dist_version} in {sdists_downloads} among {dir_contents}'
        )
    # FIXME: Does the version need to be a Version instead of str?
    source_root_dir = sources.prepare_source(wkctx, req, source_filename, dist_version)
    print(source_root_dir)


def _find_source_root_dir(work_dir, req, dist_version):
    source_root_dir = finders.find_source_dir(pathlib.Path(work_dir), req, dist_version)
    if source_root_dir:
        return source_root_dir
    work_dir_contents = list(str(e) for e in work_dir.glob('*'))
    raise RuntimeError(
        f'Cannot find source directory for {req.name} version {dist_version} among {work_dir_contents}'
    )


@step.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.pass_obj
def prepare_build(wkctx, dist_name, dist_version):
    """set up build environment to build the package

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    server.start_wheel_server(wkctx)
    req = Requirement(f'{dist_name}=={dist_version}')
    source_root_dir = _find_source_root_dir(wkctx.work_dir, req, dist_version)
    logger.info('preparing build environment for %s', req)
    sdist.prepare_build_environment(wkctx, req, source_root_dir)


@step.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.pass_obj
def build_wheel(wkctx, dist_name, dist_version):
    """build a wheel from prepared source

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    """
    req = Requirement(f'{dist_name}=={dist_version}')
    logger.info('building for %s', req)
    source_root_dir = _find_source_root_dir(wkctx.work_dir, req, dist_version)
    build_env = wheels.BuildEnvironment(wkctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(wkctx, req, source_root_dir, build_env)
    print(wheel_filename)

@step.command()
@click.option('-r', '--requirements-file', multiple=True,
              help='pip requirements file')
@click.option('--variant', default='cpu',
              help='the build variant name')
@click.argument('toplevel', nargs=-1)
@click.pass_obj
def create_build_order(wkctx, variant, requirements_file, toplevel):
    pre_built = wkctx.settings.pre_built(variant)
    if pre_built:
        logger.info('treating %s as pre-built wheels', list(sorted(pre_built)))

    server.start_wheel_server(wkctx)

    to_build = bootstrap.get_requirements_from_args(toplevel, requirements_file)

    if not to_build:
        raise RuntimeError('Pass a requirement specificiation or use -r to pass a requirements file')
    logger.debug('bootstrapping %s', to_build)
    for toplevel in to_build:
        print("wip")