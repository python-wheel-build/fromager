#!/usr/bin/env python3

import collections
import csv
import itertools
import json
import logging
import pathlib
import sys

import click
from packaging.requirements import Requirement

from . import (context, finders, overrides, sdist, server, settings, sources,
               wheels)

logger = logging.getLogger(__name__)

TERSE_LOG_FMT = '%(message)s'
VERBOSE_LOG_FMT = '%(levelname)s:%(name)s:%(lineno)d: %(message)s'


@click.group()
@click.option('-v', '--verbose', default=False)
@click.option('--log-file', type=click.Path())
@click.option('-o', '--sdists-repo', default=pathlib.Path('sdists-repo'), type=click.Path())
@click.option('-w', '--wheels-repo', default=pathlib.Path('wheels-repo'), type=click.Path())
@click.option('-t', '--work-dir', default=pathlib.Path('work-dir'), type=click.Path())
@click.option('-p', '--patches-dir', default=pathlib.Path('overrides/patches'), type=click.Path())
@click.option('-e', '--envs-dir', default=pathlib.Path('overrides/envs'), type=click.Path())
@click.option('--settings-file', default=pathlib.Path('overrides/settings.yaml'), type=click.Path())
@click.option('--wheel-server-url', default='', type=str)
@click.option('--cleanup/--no-cleanup', default=True)
@click.pass_context
def main(ctx, verbose, log_file,
         sdists_repo, wheels_repo, work_dir, patches_dir, envs_dir,
         settings_file, wheel_server_url,
         cleanup,
         ):
    # Configure console and log output.
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_formatter = logging.Formatter(VERBOSE_LOG_FMT if verbose else TERSE_LOG_FMT)
    stream_handler.setFormatter(stream_formatter)
    logging.getLogger().addHandler(stream_handler)
    if log_file:
        # Always log to the file at debug level
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(VERBOSE_LOG_FMT)
        file_handler.setFormatter(file_formatter)
        logging.getLogger().addHandler(file_handler)
    # We need to set the overall logger level to debug and allow the
    # handlers to filter messages at their own level.
    logging.getLogger().setLevel(logging.DEBUG)

    overrides.log_overrides()

    wkctx = context.WorkContext(
        settings=settings.load(settings_file),
        patches_dir=patches_dir,
        envs_dir=envs_dir,
        sdists_repo=sdists_repo,
        wheels_repo=wheels_repo,
        work_dir=work_dir,
        wheel_server_url=wheel_server_url,
        cleanup=cleanup,
    )
    wkctx.setup()
    ctx.obj = wkctx


def _get_requirements_from_args(toplevel, requirements_file):
    to_build = []
    to_build.extend(toplevel)
    for filename in requirements_file:
        with open(filename, 'r') as f:
            for line in f:
                useful, _, _ = line.partition('#')
                useful = useful.strip()
                logger.debug('line %r useful %r', line, useful)
                if not useful:
                    continue
                to_build.append(useful)
    return to_build


@main.command()
@click.option('--variant', default='cpu')
@click.option('-r', '--requirements-file', multiple=True)
@click.argument('toplevel', nargs=-1)
@click.pass_obj
def bootstrap(wkctx, variant, requirements_file, toplevel):
    "Compute and build the dependencies recursively"
    pre_built = wkctx.settings.pre_built(variant)
    if pre_built:
        logger.info('treating %s as pre-built wheels', list(sorted(pre_built)))

    server.start_wheel_server(wkctx)

    to_build = _get_requirements_from_args(toplevel, requirements_file)
    if not to_build:
        raise RuntimeError('Pass a requirement specificiation or use -r to pass a requirements file')
    logger.debug('bootstrapping %s', to_build)
    for toplevel in to_build:
        sdist.handle_requirement(wkctx, Requirement(toplevel))

    # If we put pre-built wheels in the downloads directory, we should
    # remove them so we can treat that directory as a source of wheels
    # to upload to an index.
    for prebuilt_wheel in wkctx.wheels_prebuilt.glob('*.whl'):
        filename = wkctx.wheels_downloads / prebuilt_wheel.name
        if filename.exists():
            logger.info(f'removing prebuilt wheel {prebuilt_wheel.name} from download cache')
            filename.unlink()


@main.group()
def step():
    "Step-by-step commands"
    pass


@step.command()
@click.argument('dist_name')
@click.argument('dist_version')
@click.argument('sdist_server_url')
@click.pass_obj
def download_source_archive(wkctx, dist_name, dist_version, sdist_server_url):
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
    req = Requirement(f'{dist_name}=={dist_version}')
    logger.info('building for %s', req)
    source_root_dir = _find_source_root_dir(wkctx.work_dir, req, dist_version)
    build_env = wheels.BuildEnvironment(wkctx, source_root_dir.parent, None)
    wheel_filename = wheels.build_wheel(wkctx, req, source_root_dir, build_env)
    print(wheel_filename)


@main.command()
@click.argument('dist_name', nargs=-1)
def canonicalize(dist_name):
    for name in dist_name:
        print(overrides.pkgname_to_override_module(name))


@main.group()
def build_order():
    "Commands for working with build-order files"
    pass


@build_order.command()
@click.option('-o', '--output', type=click.Path())
@click.argument('build_order_file')
def as_csv(build_order_file, output):
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
    with open(build_order_file, 'r') as f:
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

    if output:
        outfile = open(output, 'w')
    else:
        outfile = sys.stdout

    try:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()
        writer.writerows(build_order)
    finally:
        if output:
            outfile.close()


@build_order.command()
@click.option('-o', '--output', type=click.Path())
@click.argument('build_order_file', nargs=-1)
def summary(build_order_file, output):
    dist_to_input_file = collections.defaultdict(dict)
    for filename in build_order_file:
        with open(filename, 'r') as f:
            build_order = json.load(f)
        for step in build_order:
            key = overrides.pkgname_to_override_module(step['dist'])
            dist_to_input_file[key][filename] = step['version']

    if output:
        outfile = open(output, 'w')
    else:
        outfile = sys.stdout

    # The build order files are organized in directories named for the
    # image. Pull those names out of the files given.
    image_column_names = tuple(
        pathlib.Path(filename).parent.name
        for filename in build_order_file
    )

    writer = csv.writer(outfile, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(("Distribution Name",) + image_column_names + ("Same Version",))
    for dist, present_in_files in sorted(dist_to_input_file.items()):
        all_versions = set()
        row = [dist]
        for filename in build_order_file:
            v = present_in_files.get(filename, "")
            row.append(v)
            if v:
                all_versions.add(v)
        row.append(len(all_versions) == 1)
        writer.writerow(row)

    if output:
        outfile.close()


@build_order.command()
@click.option('-o', '--output', type=click.Path())
@click.argument('build_order_file', nargs=-1)
def graph(build_order_file, output):

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

    for filename in build_order_file:
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

    if output:
        outfile = open(output, 'w')
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
        if output:
            outfile.close()


if __name__ == '__main__':
    main(auto_envvar_prefix='FROMAGER')
