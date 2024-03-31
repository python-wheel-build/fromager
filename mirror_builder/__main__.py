#!/usr/bin/env python3

import argparse
import logging
import sys

from . import bootstrap, context, sdist, server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toplevel', nargs='+')
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('-o', '--sdists-repo', default='sdists-repo')
    parser.add_argument('-w', '--wheels-repo', default='wheels-repo')
    parser.add_argument('-t', '--work-dir', default='work-dir')
    parser.add_argument('--wheel-server-port', default=0, type=int)
    args = parser.parse_args(sys.argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s:%(name)s:%(lineno)d: %(message)s',
    )

    ctx = context.WorkContext(
        sdists_repo=args.sdists_repo,
        wheels_repo=args.wheels_repo,
        work_dir=args.work_dir,
        wheel_server_port=args.wheel_server_port,
    )
    ctx.setup()

    server.start_wheel_server(ctx)

    bootstrap.bootstrap_build_dependencies(ctx)

    for toplevel in args.toplevel:
        sdist.handle_requirement(ctx, toplevel)


if __name__ == '__main__':
    main()
