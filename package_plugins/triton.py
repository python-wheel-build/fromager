"""
The triton project uses branches instead of tags for their releases.

https://github.com/openai/triton/issues/3535
"""

import logging
import pathlib
import shutil

from packaging.version import Version

from mirror_builder import dependencies, external_commands, sources, wheels

logger = logging.getLogger(__name__)

GIT_URL = 'https://github.com/openai/triton.git'


def download_source(ctx, req, sdist_server_url):
    # Look on PyPI for the pre-built release that matches the
    # requirement. There's nothing to download because we're going to
    # build from a git clone, but the caller wants us to create a file
    # so we create a text file note.
    _, version = sources.resolve_sdist(req, sources.PYPI_SERVER_URL, only_sdists=False)
    source_filename = ctx.sdists_downloads / f'triton-{version}.txt'
    source_filename.write_text(f'will be cloned from {GIT_URL}')
    return source_filename, version


def prepare_source(ctx, req, source_filename, version):
    if not isinstance(version, Version):
        version = Version(version)
    dir_base = f'{req.name}-{version}'
    unpack_dir = ctx.work_dir / pathlib.Path(dir_base)
    if unpack_dir.exists():
        if ctx.cleanup:
            logger.debug('cleaning up %s', unpack_dir)
            shutil.rmtree(unpack_dir)
            unpack_dir.mkdir()
        else:
            logger.info('reusing %s', unpack_dir)
            return unpack_dir / 'triton'
    else:
        unpack_dir.mkdir()

    branch_name = f'release/{version.major}.{version.minor}.x'
    source_dir_name = _source_dir_name(version)
    output_dir_name = unpack_dir / source_dir_name

    logger.info(f'cloning {branch_name} of {GIT_URL} into {output_dir_name}')
    external_commands.run(
        ['git', 'clone', '-b', branch_name, GIT_URL, source_dir_name],
        cwd=unpack_dir,
    )
    return output_dir_name


def build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.

    # FIXME: This downloads an llvm apparently?
    return wheels.default_build_wheel(
        ctx, build_env, extra_environ, req,
        sdist_root_dir / 'python',
    )


def _source_dir_name(version):
    if not isinstance(version, Version):
        version = Version(version)
    return f'triton-{version.major}.{version.minor}.x'


def expected_source_archive_name(req, dist_version):
    return f'triton-{dist_version}.txt'


def expected_source_directory_name(req, dist_version):
    source_dir_name = _source_dir_name(dist_version)
    return f'triton-{dist_version}/{source_dir_name}'


def get_build_system_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_system_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )


def get_build_backend_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_backend_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )


def get_install_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_install_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )
