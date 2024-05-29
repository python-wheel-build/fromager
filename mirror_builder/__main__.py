#!/usr/bin/env python3

import argparse
import collections
import csv
import functools
import itertools
import json
import logging
import os
import pathlib
import sys

from packaging.requirements import Requirement
from packaging.utils import parse_wheel_filename

from . import (context, finders, jobs, overrides, rpms, sdist, server, sources,
               wheels)

logger = logging.getLogger(__name__)

TERSE_LOG_FMT = '%(message)s'
VERBOSE_LOG_FMT = '%(levelname)s:%(name)s:%(lineno)d: %(message)s'


def main():
    parser = _get_argument_parser()
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


def _get_argument_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('--log-file', default='')
    parser.add_argument('-o', '--sdists-repo', default='sdists-repo')
    parser.add_argument('-w', '--wheels-repo', default='wheels-repo')
    parser.add_argument('-t', '--work-dir', default=os.environ.get('WORKDIR', 'work-dir'))
    parser.add_argument('-p', '--patches-dir', default='overrides/patches')
    parser.add_argument('-e', '--envs-dir', default='overrides/envs')
    parser.add_argument('--wheel-server-url')
    parser.add_argument('--no-cleanup', dest='cleanup', default=True, action='store_false')
    parser.add_argument('--variant', default='cpu', choices=['cpu', 'cuda'])

    subparsers = parser.add_subparsers(title='commands', dest='command')

    parser_bootstrap = subparsers.add_parser('bootstrap')
    parser_bootstrap.set_defaults(func=do_bootstrap)
    parser_bootstrap.add_argument('--requirements', '-r')
    parser_bootstrap.add_argument('toplevel', nargs='*')

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

    parser_canonicalize = subparsers.add_parser('canonicalize')
    parser_canonicalize.set_defaults(func=do_canonicalize)
    parser_canonicalize.add_argument('toplevel', nargs='+')

    parser_pipeline_rules = subparsers.add_parser('pipeline-rules')
    parser_pipeline_rules.set_defaults(func=do_pipeline_rules)

    parser_csv = subparsers.add_parser('build-order-csv')
    parser_csv.set_defaults(func=do_build_order_csv)
    parser_csv.add_argument('build_order_file', default='work-dir/build-order.json', nargs='?')
    parser_csv.add_argument('--output', '-o')

    parser_graph = subparsers.add_parser('build-order-graph')
    parser_graph.set_defaults(func=do_build_order_graph)
    parser_graph.add_argument('build_order_file', nargs='+')
    parser_graph.add_argument('--output', '-o')

    parser_find_rpms = subparsers.add_parser('find-rpms')
    parser_find_rpms.set_defaults(func=rpms.do_find_rpms)
    parser_find_rpms.add_argument('build_order_file', default='work-dir/build-order.json')
    parser_find_rpms.add_argument('--output', '-o')

    parser_summary = subparsers.add_parser('build-order-summary')
    parser_summary.set_defaults(func=do_build_order_summary)
    parser_summary.add_argument('build_order_file', nargs='+')
    parser_summary.add_argument('--output', '-o')

    # The jobs CLI is complex enough that it's in its own module
    jobs.build_cli(parser, subparsers)

    return parser


def requires_context(f):
    "Decorate f() to add WorkContext argument before calling it."
    @functools.wraps(f)
    def provides_context(args):
        ctx = context.WorkContext(
            patches_dir=args.patches_dir,
            envs_dir=args.envs_dir,
            sdists_repo=args.sdists_repo,
            wheels_repo=args.wheels_repo,
            work_dir=args.work_dir,
            wheel_server_url=args.wheel_server_url,
            cleanup=args.cleanup,
            variant=args.variant,
        )
        ctx.setup()
        return f(args, ctx)
    return provides_context


def _get_requirements_from_args(args):
    to_build = []
    to_build.extend(args.toplevel)
    if args.requirements:
        with open(args.requirements, 'r') as f:
            for line in f:
                useful, _, _ = line.partition('#')
                useful = useful.strip()
                logger.debug('line %r useful %r', line, useful)
                if not useful:
                    continue
                to_build.append(useful)
    return to_build


@requires_context
def do_bootstrap(args, ctx):
    server.start_wheel_server(ctx)

    to_build = _get_requirements_from_args(args)
    if not to_build:
        raise RuntimeError('Pass a requirement specificiation or use -r to pass a requirements file')
    logger.debug('bootstrapping %s', to_build)
    for toplevel in to_build:
        sdist.handle_requirement(ctx, Requirement(toplevel))

    # If we put pre-built wheels in the downloads directory, we should
    # remove them so we can treat that directory as a source of wheels
    # to upload to an index.
    for prebuilt_wheel in ctx.wheels_prebuilt.glob('*.whl'):
        filename = ctx.wheels_downloads / prebuilt_wheel.name
        if filename.exists():
            logger.info(f'removing prebuilt wheel {prebuilt_wheel.name} from download cache')
            filename.unlink()


@requires_context
def do_download_source_archive(args, ctx):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('downloading source archive for %s from %s', req, args.sdist_server_url)
    filename, _ = sources.download_source(ctx, req, [args.sdist_server_url])
    print(filename)


@requires_context
def do_prepare_source(args, ctx):
    req = Requirement(f'{args.dist_name}=={args.dist_version}')
    logger.info('preparing source directory for %s', req)
    sdists_downloads = pathlib.Path(args.sdists_repo) / 'downloads'
    source_filename = finders.find_sdist(sdists_downloads, req, args.dist_version)
    if source_filename is None:
        dir_contents = []
        for ext in ['*.tar.gz', '*.zip']:
            dir_contents.extend(str(e) for e in sdists_downloads.glob(ext))
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


def do_canonicalize(args):
    for name in args.toplevel:
        print(overrides.pkgname_to_override_module(name))


@requires_context
def do_pipeline_rules(args, ctx):
    rule_template = '    - if: $CI_PIPELINE_SOURCE == "trigger" && $JOB == "build-wheel" && $DIST_NAME == "{dist_name}"'

    dist_names = sorted(
        overrides.pkgname_to_override_module(parse_wheel_filename(filename.name)[0])
        for filename in sorted(ctx.wheels_downloads.glob('*.whl'))
    )
    for dist_name in dist_names:
        print(rule_template.format(dist_name=dist_name))


def do_build_order_csv(args):
    fields = [
        ('dist', 'Distribution Name'),
        ('version', 'Version'),
        ('req', 'Original Requirement'),
        ('type', 'Dependency Type'),
        ('prebuilt', 'Pre-built Package'),
        ('order', 'Build Order'),
        ('why', 'Dependency Chain'),
    ]
    headers = {n: v for n, v in fields}
    fieldkeys = [f[0] for f in fields]
    fieldnames = [f[1] for f in fields]

    build_order = []
    with open(args.build_order_file, 'r') as f:
        for i, entry in enumerate(json.load(f), 1):
            # Add an order column, not in the original source file, in
            # case someone wants to sort the output on another field.
            entry['order'] = i
            # Replace the short keys with the longer human-readable
            # headers we want in the CSV output.
            new_entry = {headers[f]: entry[f] for f in fieldkeys}
            # Reformat the why field
            new_entry['Dependency Chain'] = ' '.join(
                f'-{dep_type}-> {Requirement(req).name}({version})'
                for dep_type, req, version
                in entry['why']
            )
            build_order.append(new_entry)

    if args.output:
        outfile = open(args.output, 'w')
    else:
        outfile = sys.stdout

    try:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(build_order)
    finally:
        if args.output:
            outfile.close()


def do_build_order_summary(args):
    dist_to_input_file = collections.defaultdict(dict)
    for filename in args.build_order_file:
        with open(filename, 'r') as f:
            build_order = json.load(f)
        for step in build_order:
            key = overrides.pkgname_to_override_module(step['dist'])
            dist_to_input_file[key][filename] = step['version']

    if args.output:
        outfile = open(args.output, 'w')
    else:
        outfile = sys.stdout

    # The build order files are organized in directories named for the
    # image. Pull those names out of the files given.
    image_column_names = tuple(
        pathlib.Path(filename).parent.name
        for filename in args.build_order_file
    )

    writer = csv.writer(outfile, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(("Distribution Name",) + image_column_names + ("Same Version",))
    for dist, present_in_files in sorted(dist_to_input_file.items()):
        all_versions = set()
        row = [dist]
        for filename in args.build_order_file:
            v = present_in_files.get(filename, "")
            row.append(v)
            if v:
                all_versions.add(v)
        row.append(len(all_versions) == 1)
        writer.writerow(row)

    if args.output:
        outfile.close()


def do_build_order_graph(args):

    def fmt_req(req, version):
        req = Requirement(req)
        name = overrides.pkgname_to_override_module(req.name)
        return f'{name}{"[" + ",".join(req.extras) + "]" if req.extras else ""}=={version}'

    def new_node(req):
        if req not in nodes:
            nodes[req] = {
                'nid': 'node' + str(next(node_ids)),
                'prebuilt': False,
            }
        return nodes[req]

    def update_node(req, prebuilt=False):
        node_details = new_node(req)
        if (not node_details['prebuilt']) and prebuilt:
            node_details['prebuilt'] = True
        return req

    # Track unique ids for nodes since the labels may not be
    # syntactically correct.
    node_ids = itertools.count(1)
    # Map formatted requirement text to node details
    nodes = {}
    edges = []

    for filename in args.build_order_file:
        with open(filename, 'r') as f:
            build_order = json.load(f)

        for step in build_order:
            update_node(fmt_req(step['dist'], step['version']), prebuilt=step['prebuilt'])
            try:
                why = step['why']
                if len(why) == 0:
                    # should not happen
                    continue
                elif len(why) == 1:
                    # Lone node requiring nothing to build.
                    pass
                else:
                    parent_info = why[0]
                    for child_info in why[1:]:
                        parent = update_node(fmt_req(parent_info[1], parent_info[2]))
                        child = update_node(fmt_req(child_info[1], child_info[2]))
                        edge = (parent, child)
                        # print(edge, nodes[edge[0]], nodes[edge[1]])
                        if edge not in edges:
                            edges.append(edge)
                        parent_info = child_info
            except Exception as err:
                raise Exception(f'Error processing {filename} at {step}') from err

    if args.output:
        outfile = open(args.output, 'w')
    else:
        outfile = sys.stdout
    try:

        outfile.write('digraph {\n')

        # Determine some nodes with special characteristics
        all_nodes = set(n['nid'] for n in nodes.values())
        # left = set(nodes[p]['nid'] for p, _ in edges)
        right = set(nodes[c]['nid'] for _, c in edges)
        # Toplevel nodes have no incoming connections
        toplevel_nodes = all_nodes - right
        # Leaves have no outgoing connections
        # leaves = all_nodes - left

        for req, node_details in nodes.items():
            nid = node_details['nid']

            node_attrs = [('label', req)]
            if node_details['prebuilt']:
                node_attrs.extend([
                    ('style', 'filled'),
                    ('color', 'darkred'),
                    ('fontcolor', 'white'),
                    ('tooltip', 'pre-built package'),
                ])
            elif nid in toplevel_nodes:
                node_attrs.extend([
                    ('style', 'filled'),
                    ('color', 'darkgreen'),
                    ('fontcolor', 'white'),
                    ('tooltip', 'toplevel package'),
                ])
            node_attr_text = ','.join('%s="%s"' % a for a in node_attrs)

            outfile.write(f'  {nid} [{node_attr_text}];\n')

        outfile.write('\n')
        if len(toplevel_nodes) > 1:
            outfile.write('  /* toplevel nodes should all be at the same level */\n')
            outfile.write('  {rank=same; %s;}\n\n' % " ".join(toplevel_nodes))
        # if len(leaves) > 1:
        #     outfile.write('  /* leaf nodes should all be at the same level */\n')
        #     outfile.write('  {rank=same; %s;}\n\n' % " ".join(leaves))

        for parent_req, child_req in edges:
            parent_node = nodes[parent_req]
            parent_nid = parent_node['nid']
            child_node = nodes[child_req]
            child_nid = child_node['nid']
            outfile.write(f'  {parent_nid} -> {child_nid};\n')

        outfile.write('}\n')
    finally:
        if args.output:
            outfile.close()


if __name__ == '__main__':
    main()
