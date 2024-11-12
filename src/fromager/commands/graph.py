import itertools
import json
import logging
import pathlib
import sys
import typing

import click
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import clickext, context
from fromager.commands import bootstrap
from fromager.dependency_graph import (
    ROOT,
    DependencyGraph,
    DependencyNode,
)
from fromager.requirements_file import RequirementType

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
    type=str,
)
@click.pass_obj
def to_constraints(wkctx: context.WorkContext, graph_file: str, output: pathlib.Path):
    "Convert a graph file to a constraints file."
    graph = DependencyGraph.from_file(graph_file)
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
    type=str,
)
@click.pass_obj
def to_dot(wkctx: context.WorkContext, graph_file: str, output: pathlib.Path):
    "Convert a graph file to a DOT file suitable to pass to graphviz."
    graph = DependencyGraph.from_file(graph_file)
    if output:
        with open(output, "w") as f:
            write_dot(graph, f)
    else:
        write_dot(graph, sys.stdout)


def write_dot(graph: DependencyGraph, output: typing.TextIO) -> None:
    install_constraints = set(node.key for node in graph.get_install_dependencies())

    output.write("digraph {\n")
    output.write("\n")

    seen_nodes = {}
    id_generator = itertools.count(1)

    def get_node_id(node):
        if node not in seen_nodes:
            seen_nodes[node] = f"node{next(id_generator)}"
        return seen_nodes[node]

    for node in graph.get_all_nodes():
        node_id = get_node_id(node.key)
        properties = f'label="{node.key}"'
        if not node:
            properties = 'label="*"'
        if node.key in install_constraints:
            properties += " style=filled fillcolor=red color=red fontcolor=white"
        else:
            properties += " style=filled fillcolor=lightgrey color=lightgrey"
        output.write(f"  {node_id} [{properties}]\n")

    output.write("\n")

    for node in graph.get_all_nodes():
        node_id = get_node_id(node.key)
        for edge in node.children:
            child_id = get_node_id(edge.destination_node.key)
            sreq = str(edge.req).replace('"', "'")
            properties = f'labeltooltip="{sreq}"'
            if edge.req_type != "install":
                properties += " style=dotted"
            output.write(f"  {node_id} -> {child_id} [{properties}]\n")
    output.write("}\n")


@graph.command()
@click.argument(
    "graph-file",
    type=str,
)
@click.pass_obj
def explain_duplicates(wkctx, graph_file):
    "Report on duplicate installation requirements, and where they come from."
    graph = DependencyGraph.from_file(graph_file)

    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts = graph.get_install_dependency_versions()

    for dep_name, nodes in sorted(conflicts.items()):
        versions = [node.version for node in nodes]
        if len(versions) == 1:
            continue

        usable_versions = {}
        user_counter = 0

        print(f"\n{dep_name}")
        for node in sorted(nodes, key=lambda x: x.version):
            print(f"  {node.version}")

            # Determine which parents can use which versions of this dependency,
            # grouping the output by the requirement specifier.
            parents_by_req = {}
            for parent_edge in node.get_incoming_install_edges():
                parents_by_req.setdefault(parent_edge.req, set()).add(
                    parent_edge.destination_node.key
                )

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


@graph.command()
@click.option(
    "--version",
    type=clickext.PackageVersion(),
    multiple=True,
    help="filter by version for the given package",
)
@click.option(
    "--depth",
    type=int,
    default=0,
    help="recursively get why each package depends on each other. Set depth to -1 for full recursion till root",
)
@click.option(
    "--requirement-type",
    type=clickext.RequirementType(),
    multiple=True,
    help="filter by requirement type",
)
@click.argument(
    "graph-file",
    type=str,
)
@click.argument("package-name", type=str)
@click.pass_obj
def why(
    wkctx: context.WorkContext,
    graph_file: str,
    package_name: str,
    version: list[Version],
    depth: int,
    requirement_type: list[RequirementType],
):
    "Explain why a dependency shows up in the graph"
    graph = DependencyGraph.from_file(graph_file)
    package_nodes = graph.get_nodes_by_name(package_name)
    if version:
        package_nodes = [node for node in package_nodes if node.version in version]
    for node in package_nodes:
        print(f"\n{node.key}")
        find_why(graph, node, depth, 1, requirement_type)


def find_why(
    graph: DependencyGraph,
    node: DependencyNode,
    max_depth: int,
    depth: int,
    req_type: list[RequirementType],
):
    all_skipped = True
    is_toplevel = False
    for parent in node.parents:
        if parent.destination_node.key == ROOT:
            is_toplevel = True
            print(f" * {node.key} is a toplevel dependency")
            continue
        if req_type and parent.req_type not in req_type:
            continue
        all_skipped = False
        print(
            f"{'  ' * depth} * is an {parent.req_type} dependency of {parent.destination_node.key} with req {parent.req}"
        )
        if max_depth and (max_depth == -1 or depth <= max_depth):
            find_why(graph, parent.destination_node, max_depth, depth + 1, [])

    if all_skipped and not is_toplevel:
        print(
            f" * couldn't find any dependencies to {node.canonicalized_name} that matches {[str(r) for r in req_type]}"
        )


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
def migrate_graph(
    wkctx: context.WorkContext, graph_file: pathlib.Path, output: pathlib.Path
):
    "Convert a old graph file into the the new format"
    graph = DependencyGraph()
    with open(graph_file, "r") as f:
        old_graph = json.load(f)
        stack = [ROOT]
        visited = set()
        while stack:
            curr_key = stack.pop()
            if curr_key in visited:
                continue
            for req_type, req_name, req_version, req in old_graph.get(curr_key, []):
                parent_name, _, parent_version = curr_key.partition("==")
                graph.add_dependency(
                    parent_name=canonicalize_name(parent_name) if parent_name else None,
                    parent_version=Version(parent_version) if parent_version else None,
                    req_type=RequirementType(req_type),
                    req_version=Version(req_version),
                    req=Requirement(req),
                )
                stack.append(f"{req_name}=={req_version}")
            visited.add(curr_key)

    if output:
        with open(output, "w") as f:
            graph.serialize(f)
    else:
        graph.serialize(sys.stdout)
