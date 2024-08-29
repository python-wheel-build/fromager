import itertools
import logging
import sys
import typing

import click

from fromager import clickext, dependency_graph
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
    graph = dependency_graph.DependencyGraph.from_file(graph_file)
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
    graph = dependency_graph.DependencyGraph.from_file(graph_file)
    if output:
        with open(output, "w") as f:
            write_dot(graph, f)
    else:
        write_dot(graph, sys.stdout)


def write_dot(graph: dependency_graph.DependencyGraph, output: typing.TextIO) -> None:
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
    type=clickext.ClickPath(),
)
@click.pass_obj
def explain_duplicates(wkctx, graph_file):
    "Report on duplicate installation requirements, and where they come from."
    graph = dependency_graph.DependencyGraph.from_file(graph_file)

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
