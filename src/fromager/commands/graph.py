import itertools
import json
import logging
import pathlib
import sys
import typing

import click
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import clickext, context
from fromager.commands import bootstrap

logger = logging.getLogger(__name__)


@click.group()
def graph():
    "Commands for working with graph files"
    pass


@graph.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
)
@click.argument(
    "graph-file",
    type=clickext.ClickPath(),
)
@click.pass_obj
def to_constraints(wkctx, graph_file, output):
    "Convert a graph file to a constraints file."
    graph = read_graph(graph_file)
    if output:
        with open(output, "w") as f:
            bootstrap.write_constraints_file(graph, f)
    else:
        bootstrap.write_constraints_file(graph, sys.stdout)


@graph.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
)
@click.argument(
    "graph-file",
    type=clickext.ClickPath(),
)
@click.pass_obj
def to_dot(wkctx, graph_file, output):
    "Convert a graph file to a DOT file suitable to pass to graphviz."
    graph = read_graph(graph_file)
    if output:
        with open(output, "w") as f:
            write_dot(graph, f)
    else:
        write_dot(graph, sys.stdout)


def write_dot(graph: context.BuildRequirements, output: typing.TextIO) -> None:
    install_constraints = set(
        f"{name}=={version}"
        for name, version, _ in bootstrap.installation_dependencies(
            all_edges=graph,
            name=context.ROOT_BUILD_REQUIREMENT,
            version=None,
        )
    )

    output.write("digraph {\n")
    output.write("\n")

    seen_nodes = {}
    id_generator = itertools.count(1)

    def get_node_id(node):
        if node not in seen_nodes:
            seen_nodes[node] = f"node{next(id_generator)}"
        return seen_nodes[node]

    def iter_nodes():
        for parent, edge_list in graph.items():
            yield parent
            for _, dist_name, dist_version, _ in edge_list:
                yield f"{dist_name}=={dist_version}"

    for node in iter_nodes():
        node_id = get_node_id(node)
        properties = f'label="{node}"'
        if not node:
            properties = 'label="*"'
        if node in install_constraints:
            properties += " style=filled fillcolor=red color=red fontcolor=white"
        else:
            properties += " style=filled fillcolor=lightgrey color=lightgrey"
        output.write(f"  {node_id} [{properties}]\n")

    output.write("\n")

    for parent, edge_list in graph.items():
        parent_id = get_node_id(parent)
        for req_type, dist_name, dist_version, req in edge_list:
            child_id = get_node_id(f"{dist_name}=={dist_version}")
            sreq = str(req).replace('"', "'")
            properties = f'labeltooltip="{sreq}"'
            if req_type != "install":
                properties += " style=dotted"
            output.write(f"  {parent_id} -> {child_id} [{properties}]\n")
    output.write("}\n")


def read_graph(filename: pathlib.Path) -> context.BuildRequirements:
    with open(filename, "r") as f:
        raw_graph = json.load(f)
    graph = {}
    for parent_key, dependencies in raw_graph.items():
        graph[parent_key] = [
            (
                req_type,
                req_name,
                Version(req_version),
                Requirement(req),
            )
            for req_type, req_name, req_version, req in dependencies
        ]
    return graph


@graph.command()
@click.argument(
    "graph-file",
    type=clickext.ClickPath(),
)
@click.pass_obj
def explain_duplicates(wkctx, graph_file):
    "Report on duplicate installation requirements, and where they come from."
    graph = read_graph(graph_file)

    # The graph shows parent->child edges. We need to look up the parent from
    # the child, so build a reverse lookup table.
    reverse_graph = bootstrap.reverse_dependency_graph(graph)

    # The installation dependencies are (name, version) pairs, and there may be
    # duplicates because multiple packages depend on the same version of another
    # package. Eliminate those duplicates using a set, so we can more easily
    # find cases where we depend on two different versions of the same thing.
    install_constraints = set(
        (name, version)
        for name, version, _ in bootstrap.installation_dependencies(
            all_edges=graph,
            name=context.ROOT_BUILD_REQUIREMENT,
            version=None,
        )
    )

    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts = {}
    for dep_name, dep_version in install_constraints:
        conflicts.setdefault(dep_name, []).append(dep_version)

    for dep_name, versions in sorted(conflicts.items()):
        if len(versions) == 1:
            continue

        usable_versions = {}
        user_counter = 0

        print(f"\n{dep_name}")
        for dep_version in sorted(versions):
            key = f"{dep_name}=={dep_version}"
            print(f"  {dep_version}")

            # Determine which parents can use which versions of this dependency,
            # grouping the output by the requirement specifier.
            parent_info = reverse_graph.get(key)
            parents_by_req = {}
            for parent_version, req in parent_info:
                parents_by_req.setdefault(req, []).append(parent_version)
            for req, parents in parents_by_req.items():
                user_counter += len(parents)
                match_versions = [str(v) for v in req.specifier.filter(versions)]
                for mv in match_versions:
                    usable_versions.setdefault(mv, []).extend(parents)
                print(f"    {req} matches {match_versions}")
                for p in parents:
                    print(f"      {p}")

        for v, users in usable_versions.items():
            if len(users) == user_counter:
                print(f"  * {dep_name}=={v} usable by all consumers")
                break
        else:
            print(f"  * No single version of {dep_name} meets all requirements")
