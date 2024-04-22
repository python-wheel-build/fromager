#!/usr/bin/env python3

import argparse
import logging
import os
import pathlib
import re
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from . import context, sdist, server, sources, wheels

logger = logging.getLogger(__name__)

TERSE_LOG_FMT = '%(message)s'
VERBOSE_LOG_FMT = '%(levelname)s:%(name)s:%(lineno)d: %(message)s'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('--log-file', default='')
    parser.add_argument('-o', '--sdists-repo', default='sdists-repo')
    parser.add_argument('-w', '--wheels-repo', default='wheels-repo')
    parser.add_argument('-t', '--work-dir', default=os.environ.get('WORKDIR', 'work-dir'))
    parser.add_argument('--wheel-server-url')
    parser.add_argument('--no-cleanup', dest='cleanup', default=True, action='store_false')

    subparsers = parser.add_subparsers(title='commands', dest='command')

    parser_bootstrap = subparsers.add_parser('bootstrap')
    parser_bootstrap.set_defaults(func=do_bootstrap)
    parser_bootstrap.add_argument('toplevel', nargs='+')

    parser_download = subparsers.add_parser('download-source-archive')
    parser_download.set_defaults(func=do_download_source_archive)
    parser_download.add_argument('dist_name')
    parser_download.add_argument('dist_version')

    parser_prepare_source = subparsers.add_parser('prepare-source')
    parser_prepare_source.set_defaults(func=do_prepare_source)
    parser_prepare_source.add_argument('dist_name')
    parser_prepare_source.add_argument('dist_version')

    parser_prepare_build = subparsers.add_parser('prepare-build')
    parser_prepare_build.set_defaults(func=do_prepare_build)
    parser_prepare_build.add_argument('dist_name')
    parser_prepare_build.add_argument('dist_version')

    parser_build = subparsers.add_parser('build')
    parser_build.set_defaults(func=do_build)
    parser_build.add_argument('dist_name')
    parser_build.add_argument('dist_version')

    args = parser.parse_args(sys.argv[1:])

    # Configure console and log output.
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    stream_formatter = logging.Formatter(VERBOSE_LOG_FMT if args.verbose else TERSE_LOG_FMT)
    stream_handler.setFormatter(stream_formatter)
    logging.getLogger().addHandler(stream_handler)
    if args.log_file:
        # Always log to the file at debug level
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(VERBOSE_LOG_FMT)
        file_handler.setFormatter(file_formatter)
        logging.getLogger().addHandler(file_handler)
    # We need to set the overall logger level to debug and allow the
    # handlers to filter messages at their own level.
    logging.getLogger().setLevel(logging.DEBUG)

    ctx = context.WorkContext(
        sdists_repo=args.sdists_repo,
        wheels_repo=args.wheels_repo,
        work_dir=args.work_dir,
        wheel_server_url=args.wheel_server_url,
        cleanup=args.cleanup,
    )
    ctx.setup()

    args.func(ctx, args)


def do_bootstrap(ctx, args):
    server.start_wheel_server(ctx)
    for toplevel in args.toplevel:
        sdist.handle_requirement(ctx, Requirement(toplevel))


def do_download_source_archive(ctx, args):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('downloading source archive for %s', req)
    filename, _ = sources.download_source(ctx, req)
    print(filename)


def do_prepare_source(ctx, args):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('preparing source directory for %s', req)
    source_filename = _find_sdist(pathlib.Path(args.sdists_repo), req, args.dist_version)
    # FIXME: Does the version need to be a Version instead of str?
    source_root_dir = sources.prepare_source(ctx, req, source_filename, args.dist_version)
    print(source_root_dir)


def _dist_name_to_filename(dist_name):
    """Transform the dist name into a prefix for a filename.

    Following https://peps.python.org/pep-0427/
    """
    canonical_name = canonicalize_name(dist_name)
    return re.sub(r"[^\w\d.]+", "_", canonical_name, re.UNICODE)


def _find_sdist(sdists_repo, req, dist_version):
    downloads_dir = sdists_repo / 'downloads'
    filename_prefix = _dist_name_to_filename(req.name)
    canonical_name = canonicalize_name(req.name)
    candidates = [
        # First check if the file is there using the canonically
        # transformed name.
        downloads_dir / f'{filename_prefix}-{dist_version}.tar.gz',
        # If that didn't work, try the canonical dist name. That's not
        # "correct" but we do see it. (charset-normalizer-3.3.2.tar.gz
        # and setuptools-scm-8.0.4.tar.gz) for example
        downloads_dir / f'{canonical_name}-{dist_version}.tar.gz',
    ]
    for sdist_file in candidates:
        if sdist_file.exists():
            return sdist_file
    raise RuntimeError(
        f'Cannot find sdist for {req.name} version {dist_version} in {candidates}'
    )


def _find_source_dir(work_dir, req, dist_version):
    filename_prefix = _dist_name_to_filename(req.name)
    filename_based = f'{filename_prefix}-{dist_version}'
    canonical_name = canonicalize_name(req.name)
    canonical_based = f'{canonical_name}-{dist_version}'
    candidates = [
        # First check if the file is there using the canonically
        # transformed name.
        work_dir / filename_based / filename_based,
        # If that didn't work, try the canonical dist name. That's not
        # "correct" but we do see it. (charset-normalizer-3.3.2.tar.gz
        # and setuptools-scm-8.0.4.tar.gz) for example
        work_dir / canonical_based / canonical_based,
    ]
    for source_dir in candidates:
        if source_dir.exists():
            return source_dir

    raise RuntimeError(
        f'Cannot find source directory for {req.name} version {dist_version} in {candidates}'
    )


def do_prepare_build(ctx, args):
    server.start_wheel_server(ctx)
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    source_root_dir = _find_source_dir(pathlib.Path(args.work_dir), req, args.dist_version)
    logger.info('preparing build environment for %s', req)
    sdist.prepare_build_environment(ctx, req, source_root_dir)


def do_build(ctx, args):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('building for %s', req)
    source_root_dir = _find_source_dir(pathlib.Path(args.work_dir), req, args.dist_version)
    build_env = wheels.BuildEnvironment(ctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(ctx, req, source_root_dir, build_env)
    print(wheel_filename)


if __name__ == '__main__':
    main()
