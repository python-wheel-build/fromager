#!/usr/bin/env python3

import argparse
import functools
import logging
import os
import pathlib
import sys

from packaging.requirements import Requirement

from . import context, finders, jobs, sdist, server, sources, wheels

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
    parser_download.add_argument('sdist_server_url')

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

    # The jobs CLI is complex enough that it's in its own module
    jobs.build_cli(parser, subparsers)

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

    try:
        args.func(args)
    except Exception as err:
        logger.exception(err)
        raise


def requires_context(f):
    "Decorate f() to add WorkContext argument before calling it."
    @functools.wraps(f)
    def provides_context(args):
        ctx = context.WorkContext(
            sdists_repo=args.sdists_repo,
            wheels_repo=args.wheels_repo,
            work_dir=args.work_dir,
            wheel_server_url=args.wheel_server_url,
            cleanup=args.cleanup,
        )
        ctx.setup()
        return f(args, ctx)
    return provides_context


@requires_context
def do_bootstrap(args, ctx):
    server.start_wheel_server(ctx)
    for toplevel in args.toplevel:
        sdist.handle_requirement(ctx, Requirement(toplevel))


@requires_context
def do_download_source_archive(args, ctx):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('downloading source archive for %s from %s', req, args.sdist_server_url)
    filename, _ = sources.download_source(ctx, req, args.sdist_server_url)
    print(filename)


@requires_context
def do_prepare_source(args, ctx):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('preparing source directory for %s', req)
    sdists_downloads = pathlib.Path(args.sdists_repo) / 'downloads'
    source_filename = finders.find_sdist(sdists_downloads, req, args.dist_version)
    if source_filename is None:
        dir_contents = [str(e) for e in sdists_downloads.glob('*.tar.gz')]
        raise RuntimeError(
            f'Cannot find sdist for {req.name} version {args.dist_version} in {sdists_downloads} among {dir_contents}'
        )
    # FIXME: Does the version need to be a Version instead of str?
    source_root_dir = sources.prepare_source(ctx, req, source_filename, args.dist_version)
    print(source_root_dir)


def _find_source_root_dir(work_dir, req, dist_version):
    source_root_dir = finders.find_source_dir(pathlib.Path(work_dir), req, dist_version)
    if source_root_dir:
        return source_root_dir
    work_dir_contents = list(str(e) for e in work_dir.glob('*'))
    raise RuntimeError(
        f'Cannot find source directory for {req.name} version {dist_version} among {work_dir_contents}'
    )


@requires_context
def do_prepare_build(args, ctx):
    server.start_wheel_server(ctx)
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    source_root_dir = _find_source_root_dir(pathlib.Path(args.work_dir), req, args.dist_version)
    logger.info('preparing build environment for %s', req)
    sdist.prepare_build_environment(ctx, req, source_root_dir)


@requires_context
def do_build(args, ctx):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('building for %s', req)
    source_root_dir = _find_source_root_dir(pathlib.Path(args.work_dir), req, args.dist_version)
    build_env = wheels.BuildEnvironment(ctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(ctx, req, source_root_dir, build_env)
    print(wheel_filename)


if __name__ == '__main__':
    main()
