#!/usr/bin/env python3

import argparse
import logging
import os
import pathlib
import sys

from packaging.requirements import Requirement

from . import context, sdist, server, sources, wheels

TERSE_LOG_FMT = '%(message)s'
VERBOSE_LOG_FMT = '%(levelname)s:%(name)s:%(lineno)d: %(message)s'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('-o', '--sdists-repo', default='sdists-repo')
    parser.add_argument('-w', '--wheels-repo', default='wheels-repo')
    parser.add_argument('-t', '--work-dir', default=os.environ.get('WORKDIR', 'work-dir'))
    parser.add_argument('--wheel-server-port', default=0, type=int)
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
    parser_prepare_source.add_argument('source_archive')

    parser_prepare_build = subparsers.add_parser('prepare-build')
    parser_prepare_build.set_defaults(func=do_prepare_build)
    parser_prepare_build.add_argument('dist_name')
    parser_prepare_build.add_argument('dist_version')
    parser_prepare_build.add_argument('source_dir')

    parser_build = subparsers.add_parser('build')
    parser_build.set_defaults(func=do_build)
    parser_build.add_argument('dist_name')
    parser_build.add_argument('dist_version')
    parser_build.add_argument('source_dir')

    args = parser.parse_args(sys.argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=VERBOSE_LOG_FMT if args.verbose else TERSE_LOG_FMT,
    )

    ctx = context.WorkContext(
        sdists_repo=args.sdists_repo,
        wheels_repo=args.wheels_repo,
        work_dir=args.work_dir,
        wheel_server_port=args.wheel_server_port,
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
    filename, _ = sources.download_source(ctx, req)
    with open(ctx.work_dir / 'last-download.txt', 'w') as f:
        f.write(filename)
    print(filename)


def do_prepare_source(ctx, args):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    source_filename = pathlib.Path(args.source_archive)
    # FIXME: Does the version need to be a Version instead of str?
    source_root_dir = sources.prepare_source(ctx, req, source_filename, args.dist_version)
    with open(ctx.work_dir / 'last-source-dir.txt', 'w') as f:
        f.write(str(source_root_dir))
    print(source_root_dir)


def do_prepare_build(ctx, args):
    server.start_wheel_server(ctx)
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    source_root_dir = pathlib.Path(args.source_dir)
    sdist.prepare_build_environment(ctx, req, source_root_dir)


def do_build(ctx, args):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    source_root_dir = pathlib.Path(args.source_dir)
    build_env = wheels.BuildEnvironment(ctx, source_root_dir.parent, None)
    wheel_filenames = wheels.build_wheel(ctx, req, source_root_dir, build_env)
    with open(ctx.work_dir / 'last-wheels.txt', 'w') as f:
        for filename in wheel_filenames:
            f.write(f'{filename}\n')
            print(filename)


if __name__ == '__main__':
    main()
