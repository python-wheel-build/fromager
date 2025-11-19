import io
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
from fromager.packagesettings import PatchMap
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
    graph: DependencyGraph = DependencyGraph.from_file(graph_file)

    if output:
        # Use a temporary buffer first to avoid creating the file if there are conflicts
        buffer = io.StringIO()
        ret = bootstrap.write_constraints_file(graph, buffer)

        if not ret:
            raise ValueError(
                "Failed to write constraints file - no valid set of installation dependencies could be generated"
            )

        # Only create the output file if constraint resolution succeeded
        with open(output, "w") as f:
            f.write(buffer.getvalue())
    else:
        ret = bootstrap.write_constraints_file(graph, sys.stdout)
        if not ret:
            raise ValueError(
                "Failed to generate constraints - no single version set satisfies all requirements"
            )


@graph.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    default=None,
)
@click.option(
    "--install-only",
    is_flag=True,
    help="Only show installation dependencies, excluding build dependencies",
)
@click.option(
    "--overrides-only",
    is_flag=True,
    help="Only include nodes with fromager overrides (settings, patches, or plugins)",
)
@click.argument(
    "graph-file",
    type=str,
)
@click.pass_obj
def to_dot(
    wkctx: context.WorkContext,
    graph_file: str,
    output: pathlib.Path | None,
    install_only: bool,
    overrides_only: bool,
):
    "Convert a graph file to a DOT file suitable to pass to graphviz."
    graph = DependencyGraph.from_file(graph_file)
    if output:
        with open(output, "w") as f:
            write_dot(wkctx, graph, f, install_only=install_only, reduce=overrides_only)
    else:
        write_dot(
            wkctx, graph, sys.stdout, install_only=install_only, reduce=overrides_only
        )


def _get_nodes_for_reduction(
    graph: DependencyGraph,
    install_only: bool,
) -> list[DependencyNode]:
    """Determine starting node set based on install_only flag."""
    if install_only:
        nodes: list[DependencyNode] = [graph.nodes[ROOT]]
        nodes.extend(graph.get_install_dependencies())
        return nodes
    return list(graph.get_all_nodes())


def _find_customized_nodes(
    wkctx: context.WorkContext,
    nodes: list[DependencyNode],
) -> list[DependencyNode]:
    """Filter nodes to find only those with customizations."""
    customized_nodes: list[DependencyNode] = []
    for node in nodes:
        pbi = wkctx.settings.package_build_info(node.canonicalized_name)
        if node.canonicalized_name != ROOT and pbi.has_customizations:
            customized_nodes.append(node)
    return customized_nodes


def _find_customized_dependencies_for_node(
    wkctx: context.WorkContext,
    node: DependencyNode,
    install_only: bool,
) -> dict[str, str]:
    """
    Find all reachable customized nodes from a given node using depth-first search.

    Returns:
        Dictionary mapping child keys to their requirement strings.
        Format: {child_key: requirement_string}
    """
    dependencies: dict[str, str] = {}
    visited: set[str] = set()
    # Stack contains: (current_node, path_from_start, original_requirement)
    stack: list[tuple[DependencyNode, list[str], str | None]] = [(node, [], None)]

    while stack:
        current_node, path, original_req = stack.pop()

        if current_node.key in visited:
            continue
        visited.add(current_node.key)

        for edge in current_node.children:
            # Skip build dependencies if install_only is True
            if install_only and edge.req_type.is_build_requirement:
                continue

            child = edge.destination_node
            child_pbi = wkctx.settings.package_build_info(child.canonicalized_name)
            new_path = path + [current_node.key]

            # Use the first requirement we encounter in the path
            current_req = original_req if original_req else str(edge.req)

            # If the child has customizations, add it as a direct dependency
            if child_pbi.has_customizations:
                dependencies[child.key] = current_req
            else:
                # If the child doesn't have customizations, continue traversing
                stack.append((child, new_path, current_req))

    return dependencies


def _build_reduced_dependency_map(
    wkctx: context.WorkContext,
    customized_nodes: list[DependencyNode],
    install_only: bool,
) -> dict[str, dict[str, str]]:
    """Build dependency map for all customized nodes."""
    reduced_dependencies: dict[str, dict[str, str]] = {}
    for node in customized_nodes:
        reduced_dependencies[node.key] = _find_customized_dependencies_for_node(
            wkctx, node, install_only
        )
    return reduced_dependencies


def reduce_graph(
    wkctx: context.WorkContext,
    graph: DependencyGraph,
    overridden_packages: set[str],
    install_only: bool = False,
) -> tuple[list[DependencyNode], dict[str, dict[str, str]]]:
    """
    Reduce the graph to only include nodes with customizations.

    Returns:
        - List of nodes to include in the reduced graph
        - Dictionary mapping each included node to its direct dependencies with requirement info
          Format: {parent_key: {child_key: requirement_string}}
    """
    # Get starting node set based on install_only flag
    all_nodes = _get_nodes_for_reduction(graph, install_only)

    # Find nodes with customizations
    customized_nodes = _find_customized_nodes(wkctx, all_nodes)

    # Build reduced dependency relationships with requirement tracking
    reduced_dependencies = _build_reduced_dependency_map(
        wkctx, customized_nodes, install_only
    )

    return customized_nodes, reduced_dependencies


def write_dot(
    wkctx: context.WorkContext,
    graph: DependencyGraph,
    output: typing.TextIO,
    install_only: bool = False,
    reduce: bool = False,
) -> None:
    install_constraints = set(node.key for node in graph.get_install_dependencies())
    overridden_packages: set[str] = set(wkctx.settings.list_overrides())

    output.write("digraph {\n")
    output.write("\n")

    seen_nodes: dict[str, str] = {}
    id_generator = itertools.count(1)

    def get_node_id(node: str) -> str:
        if node not in seen_nodes:
            seen_nodes[node] = f"node{next(id_generator)}"
        return seen_nodes[node]

    _node_shape_properties = {
        "build_settings": "shape=box",
        "build": "shape=oval",
        "default": "shape=oval",
        "patches": "shape=note",
        "plugin_and_patches": "shape=tripleoctagon",
        "plugin": "shape=trapezium",
        "pre_built": "shape=parallelogram",
        "toplevel": "shape=circle",
    }

    # Determine which nodes to include
    if reduce:
        nodes_to_include, reduced_dependencies = reduce_graph(
            wkctx, graph, overridden_packages, install_only
        )
    elif install_only:
        nodes_to_include = [graph.nodes[ROOT]]
        nodes_to_include.extend(graph.get_install_dependencies())
        reduced_dependencies = None
    else:
        nodes_to_include = list(graph.get_all_nodes())
        reduced_dependencies = None

    for node in sorted(nodes_to_include, key=lambda x: x.key):
        node_id = get_node_id(node.key)

        if not node:
            label = "*"
        else:
            label = node.key

        node_type: list[str] = []
        name = node.canonicalized_name
        if not name:
            node_type.append("toplevel")
        else:
            pbi = wkctx.settings.package_build_info(name)
            all_patches: PatchMap = pbi.get_all_patches()

            if node.pre_built:
                node_type.append("pre_built")
            elif pbi.plugin and all_patches:
                node_type.append("plugin_and_patches")
            elif pbi.plugin:
                node_type.append("plugin")
            elif all_patches:
                node_type.append("patches")
            elif name in overridden_packages:
                node_type.append("build_settings")
            else:
                node_type.append("default")

        style = "filled"
        if not install_only:
            if node.key in install_constraints or node.key == ROOT:
                style += ",bold"
            else:
                style += ",dashed"

        properties = f'label="{label}" style="{style}" color=black fillcolor=white fontcolor=black '
        properties += " ".join(_node_shape_properties[t] for t in node_type)

        output.write(f"  {node_id} [{properties}]\n")

    output.write("\n")

    # Create a set of included node keys for efficient lookup
    included_node_keys = {node.key for node in nodes_to_include}

    known_edges: set[tuple[str, str]] = set()

    if reduce and reduced_dependencies:
        # Use the reduced dependency relationships
        for node_key, child_deps in reduced_dependencies.items():
            node_id = get_node_id(node_key)
            for child_key, req_str in child_deps.items():
                # Skip duplicate edges
                if (node_key, child_key) in known_edges:
                    continue
                known_edges.add((node_key, child_key))

                child_id = get_node_id(child_key)
                # Use the actual requirement string from the reduced graph
                sreq = req_str.replace('"', "'")
                properties = f'labeltooltip="{sreq}"'
                # For reduced graphs, we assume these are install dependencies (solid lines)

                output.write(f"  {node_id} -> {child_id} [{properties}]\n")
    else:
        # Use the original edge generation logic
        for node in nodes_to_include:
            node_id = get_node_id(node.key)
            for edge in node.children:
                # Skip edges if we're in install-only mode and the edge is a build dependency
                if install_only and edge.req_type.is_build_requirement:
                    continue

                # Skip duplicate edges
                if (node.key, edge.destination_node.key) in known_edges:
                    continue
                known_edges.add((node.key, edge.destination_node.key))

                # Skip edges to nodes that aren't included
                if edge.destination_node.key not in included_node_keys:
                    continue

                child_id = get_node_id(edge.destination_node.key)
                sreq = str(edge.req).replace('"', "'")
                properties = f'labeltooltip="{sreq}"'
                if edge.req_type.is_build_requirement:
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
    show_explain_duplicates(graph)


def show_explain_duplicates(graph: DependencyGraph) -> None:
    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts = graph.get_install_dependency_versions()

    for dep_name, nodes in sorted(conflicts.items()):
        versions = [node.version for node in nodes]
        if len(versions) == 1:
            continue

        usable_versions: dict[str, list[str]] = {}
        user_counter: int = 0

        # Get the constraint from the first node (all versions have the same constraint)
        constraint_info = (
            f" (constraint: {nodes[0].constraint})" if nodes[0].constraint else ""
        )
        print(f"\n{dep_name}{constraint_info}")
        for node in sorted(nodes, key=lambda x: x.version):
            print(f"  {node.version}")

            # Determine which parents can use which versions of this dependency,
            # grouping the output by the requirement specifier.
            parents_by_req: dict[Requirement, set[str]] = {}
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
        find_why(graph, node, depth, 0, requirement_type)


def find_why(
    graph: DependencyGraph,
    node: DependencyNode,
    max_depth: int,
    depth: int,
    req_type: list[RequirementType],
    seen: set[str] | None = None,
) -> None:
    if seen is None:
        seen = set()

    if node.key in seen:
        print(f"{'  ' * depth} * {node.key} has a cycle")
        return

    # Print the name of the package we are asking about. We do this here because
    # we might be invoked for multiple packages and we want the format to be
    # consistent.
    if depth == 0:
        constraint_info = f" (constraint: {node.constraint})" if node.constraint else ""
        print(f"\n{node.key}{constraint_info}")

    seen = set([node.key]).union(seen)
    all_skipped = True
    is_toplevel = False
    for parent in node.parents:
        # Show the toplevel dependencies regardless of the req_type because they
        # are the ones that are actually installed and may influence other
        # dependencies.
        if parent.destination_node.key == ROOT:
            is_toplevel = True
            # Show constraint for top-level dependencies
            constraint_info = (
                f" (constraint: {node.constraint})" if node.constraint else ""
            )
            print(
                f"{'  ' * depth} * {node.key}{constraint_info} is a toplevel dependency with req {parent.req}"
            )
            continue
        # Skip dependencies that don't match the req_type.
        if req_type and parent.req_type not in req_type:
            continue
        all_skipped = False
        parent_constraint = (
            f" (constraint: {parent.destination_node.constraint})"
            if parent.destination_node.constraint
            else ""
        )
        print(
            f"{'  ' * depth} * {node.key} is an {parent.req_type} dependency of {parent.destination_node.key}{parent_constraint} with req {parent.req}"
        )
        if max_depth and (max_depth == -1 or depth <= max_depth):
            find_why(
                graph=graph,
                node=parent.destination_node,
                max_depth=max_depth,
                depth=depth + 1,
                req_type=req_type,
                seen=seen,
            )

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


@graph.command()
@click.argument(
    "graph-file",
    type=clickext.ClickPath(),
)
@click.pass_obj
def build_graph(
    wkctx: context.WorkContext,
    graph_file: pathlib.Path,
):
    """Print build graph steps for parallel-build

    The build-graph command takes a graph.json file and analyzes in which
    order parallel build is going to build the wheels. It also shows which
    wheels are recognized as build dependencies or exclusive builds.
    """
    graph = DependencyGraph.from_file(graph_file)
    topo = graph.get_build_topology(context=wkctx)
    topo.prepare()

    def n2s(nodes: typing.Iterable[DependencyNode]) -> str:
        return ", ".join(sorted(node.key for node in nodes))

    print(f"Build dependencies ({len(topo.dependency_nodes)}):")
    print(n2s(topo.dependency_nodes), "\n")
    if topo.exclusive_nodes:
        print(f"Exclusive builds ({len(topo.exclusive_nodes)}):")
        print(n2s(topo.exclusive_nodes), "\n")

    print("Build rounds:")
    rounds: int = 0
    while topo.is_active():
        rounds += 1
        nodes_to_build = topo.get_available()
        print(f"{rounds}.", n2s(nodes_to_build))
        topo.done(*nodes_to_build)

    print(f"\nBuilding {len(graph)} packages in {rounds} rounds.")
