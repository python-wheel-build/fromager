import io
import itertools
import json
import logging
import math
import pathlib
import sys
import typing

import click
import rich
import rich.box
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version
from rich.table import Table

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
def graph() -> None:
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
def to_constraints(
    wkctx: context.WorkContext, graph_file: str, output: pathlib.Path
) -> None:
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
) -> None:
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
def explain_duplicates(wkctx: context.WorkContext, graph_file: str) -> None:
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
) -> None:
    "Explain why a dependency shows up in the graph"
    graph = DependencyGraph.from_file(graph_file)
    package_nodes = graph.get_nodes_by_name(package_name)
    if version:
        package_nodes = [node for node in package_nodes if node.version in version]
    for node in package_nodes:
        find_why(graph, node, depth, 0, requirement_type)


@graph.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    help="Output file path for the subset graph",
)
@click.option(
    "--version",
    type=clickext.PackageVersion(),
    help="Limit subset to specific version of the package",
)
@click.argument(
    "graph-file",
    type=str,
)
@click.argument("package-name", type=str)
@click.pass_obj
def subset(
    wkctx: context.WorkContext,
    graph_file: str,
    package_name: str,
    output: pathlib.Path | None,
    version: Version | None,
) -> None:
    """Extract a subset of a build graph related to a specific package.

    Creates a new graph containing only nodes that depend on the specified package
    and the dependencies of that package. By default includes all versions of the
    package, but can be limited to a specific version with --version.
    """
    try:
        graph = DependencyGraph.from_file(graph_file)
        subset_graph = extract_package_subset(graph, package_name, version)

        if output:
            with open(output, "w") as f:
                subset_graph.serialize(f)
        else:
            subset_graph.serialize(sys.stdout)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def extract_package_subset(
    graph: DependencyGraph,
    package_name: str,
    version: Version | None = None,
) -> DependencyGraph:
    """Extract a subset of the graph containing nodes related to a specific package.

    Creates a new graph containing:
    - All nodes matching the package name (optionally filtered by version)
    - All nodes that depend on the target package (dependents)
    - All dependencies of the target package

    Args:
        graph: The source dependency graph
        package_name: Name of the package to extract subset for
        version: Optional version to filter target nodes

    Returns:
        A new DependencyGraph containing only the related nodes

    Raises:
        ValueError: If package not found in graph
    """
    # Find target nodes matching the package name
    target_nodes = graph.get_nodes_by_name(package_name)
    if version:
        target_nodes = [node for node in target_nodes if node.version == version]

    if not target_nodes:
        version_msg = f" version {version}" if version else ""
        raise ValueError(f"Package {package_name}{version_msg} not found in graph")

    # Collect all related nodes
    related_nodes: set[str] = set()

    # Add target nodes
    for node in target_nodes:
        related_nodes.add(node.key)

    # Traverse up to find dependents (what depends on our package)
    visited_up: set[str] = set()
    for target_node in target_nodes:
        _collect_dependents(target_node, related_nodes, visited_up)

    # Traverse down to find dependencies (what our package depends on)
    visited_down: set[str] = set()
    for target_node in target_nodes:
        _collect_dependencies(target_node, related_nodes, visited_down)

    # Create new graph with only related nodes
    subset_graph = DependencyGraph()
    _build_subset_graph(graph, subset_graph, related_nodes)

    return subset_graph


def _collect_dependents(
    node: DependencyNode,
    related_nodes: set[str],
    visited: set[str],
) -> None:
    """Recursively collect all nodes that depend on the given node."""
    if node.key in visited:
        return
    visited.add(node.key)

    for parent_edge in node.parents:
        parent_node = parent_edge.destination_node
        related_nodes.add(parent_node.key)
        _collect_dependents(parent_node, related_nodes, visited)


def _collect_dependencies(
    node: DependencyNode,
    related_nodes: set[str],
    visited: set[str],
) -> None:
    """Recursively collect all dependencies of the given node."""
    if node.key in visited:
        return
    visited.add(node.key)

    for child_edge in node.children:
        child_node = child_edge.destination_node
        related_nodes.add(child_node.key)
        _collect_dependencies(child_node, related_nodes, visited)


def _build_subset_graph(
    source_graph: DependencyGraph,
    target_graph: DependencyGraph,
    included_nodes: set[str],
) -> None:
    """Build the subset graph with only the included nodes and their edges."""
    # First pass: add all included nodes
    for node_key in included_nodes:
        source_node = source_graph.nodes[node_key]
        if node_key == ROOT:
            continue  # ROOT is already created in the new graph

        # Add the node to target graph
        target_graph._add_node(
            req_name=source_node.canonicalized_name,
            version=source_node.version,
            download_url=source_node.download_url,
            pre_built=source_node.pre_built,
            constraint=source_node.constraint,
        )

    # Second pass: add edges between included nodes
    for node_key in included_nodes:
        source_node = source_graph.nodes[node_key]
        for child_edge in source_node.children:
            child_key = child_edge.destination_node.key
            # Only add edge if both parent and child are in the subset
            if child_key in included_nodes:
                child_node = child_edge.destination_node
                target_graph.add_dependency(
                    parent_name=source_node.canonicalized_name
                    if source_node.canonicalized_name
                    else None,
                    parent_version=source_node.version
                    if source_node.canonicalized_name
                    else None,
                    req_type=child_edge.req_type,
                    req=child_edge.req,
                    req_version=child_node.version,
                    download_url=child_node.download_url,
                    pre_built=child_node.pre_built,
                    constraint=child_node.constraint,
                )


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
) -> None:
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
) -> None:
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


def _get_collection_name(graph_path: str) -> str:
    """Derive collection name from file path stem."""
    return pathlib.Path(graph_path).stem


def _get_collection_packages(graph_path: str) -> set[NormalizedName]:
    """Load graph and return all canonical package names, excluding ROOT."""
    graph = DependencyGraph.from_file(graph_path)
    return {
        node.canonicalized_name
        for node in graph.get_all_nodes()
        if node.canonicalized_name != ROOT
    }


def _find_shared_packages(
    collections: dict[str, set[NormalizedName]],
    min_collections: int,
    display_names: dict[str, str] | None = None,
) -> list[dict[str, typing.Any]]:
    """Find packages in >= min_collections collections, sorted by count desc then name asc."""
    all_packages: set[NormalizedName] = set().union(*collections.values())
    results: list[dict[str, typing.Any]] = []
    for pkg in all_packages:
        containing = [
            display_names.get(key, key) if display_names else key
            for key, pkgs in collections.items()
            if pkg in pkgs
        ]
        if len(containing) >= min_collections:
            results.append(
                {
                    "package": pkg,
                    "collections": sorted(containing),
                    "count": len(containing),
                }
            )
    results.sort(key=lambda x: (-x["count"], x["package"]))
    return results


def _compute_collection_impact(
    collections: dict[str, set[NormalizedName]],
    base_package_names: set[NormalizedName],
    display_names: dict[str, str] | None = None,
) -> list[dict[str, typing.Any]]:
    """For each collection, compute how many packages remain after removing base packages.

    Each entry includes per-remaining-package cross-collection counts.
    Sorted by remaining package count descending, then collection name ascending.
    """
    all_packages: set[NormalizedName] = set().union(*collections.values())
    pkg_counts: dict[NormalizedName, int] = {
        pkg: sum(1 for pkgs in collections.values() if pkg in pkgs)
        for pkg in all_packages
    }

    result = []
    for key, pkgs in collections.items():
        coll_name = display_names.get(key, key) if display_names else key
        base_pkgs = pkgs & base_package_names
        remaining_pkgs = pkgs - base_package_names
        remaining_detail = sorted(
            [
                {"package": pkg, "collection_count": pkg_counts[pkg]}
                for pkg in remaining_pkgs
            ],
            key=lambda x: (
                -typing.cast(int, x["collection_count"]),
                typing.cast(str, x["package"]),
            ),
        )
        result.append(
            {
                "collection": coll_name,
                "total_packages": len(pkgs),
                "base_packages": len(base_pkgs),
                "remaining_packages": len(remaining_pkgs),
                "reduction_percentage": (
                    round(len(base_pkgs) / len(pkgs) * 100, 1) if pkgs else 0.0
                ),
                "remaining": remaining_detail,
            }
        )
    result.sort(
        key=lambda x: (
            -typing.cast(int, x["remaining_packages"]),
            typing.cast(str, x["collection"]),
        )
    )
    return result


def _suggest_base_table(
    candidates: list[dict[str, typing.Any]],
    total_collections: int,
    collection_names: list[str],
    min_collections: int,
    base_packages: set[NormalizedName] | None,
    total_unique_packages: int,
    impact: list[dict[str, typing.Any]],
    base_only_packages: set[NormalizedName],
) -> None:
    """Display suggest-base results as a rich table."""
    title = (
        f"Base collection candidates "
        f"(threshold: {min_collections}/{total_collections} collections)\n"
        f"Collections: {', '.join(sorted(collection_names))}"
    )
    table = Table(title=title, box=rich.box.MARKDOWN, title_justify="left")
    table.add_column("Package", justify="left", no_wrap=True)
    table.add_column("Collections", justify="right", no_wrap=True)
    table.add_column("Coverage", justify="right", no_wrap=True)
    table.add_column("Appears In", justify="left")
    if base_packages is not None:
        table.add_column("In Base", justify="center", no_wrap=True)

    already_in_base = 0
    new_candidates = 0
    for entry in candidates:
        pkg = entry["package"]
        count = entry["count"]
        cols = entry["collections"]
        coverage = f"{(count / total_collections) * 100:.1f}%"
        count_str = f"{count}/{total_collections}"
        appears_in = ", ".join(cols)
        if base_packages is not None:
            in_base = pkg in base_packages
            if in_base:
                already_in_base += 1
            else:
                new_candidates += 1
            table.add_row(
                pkg, count_str, coverage, appears_in, "yes" if in_base else "no"
            )
        else:
            new_candidates += 1
            table.add_row(pkg, count_str, coverage, appears_in)

    console = rich.get_console()
    console.print(table)
    console.print(f"\nTotal unique packages: {total_unique_packages}")
    console.print(f"Packages in >= {min_collections} collections: {len(candidates)}")
    if base_packages is not None:
        console.print(f"Already in base: {already_in_base}")
        console.print(f"New candidates: {new_candidates}")

    # Collection Impact table
    impact_table = Table(
        title="Collection Impact", box=rich.box.MARKDOWN, title_justify="left"
    )
    impact_table.add_column("Collection", justify="left", no_wrap=True)
    impact_table.add_column("Total Pkgs", justify="right", no_wrap=True)
    impact_table.add_column("In Base", justify="right", no_wrap=True)
    impact_table.add_column("Remaining", justify="right", no_wrap=True)
    impact_table.add_column("% Saved", justify="right", no_wrap=True)
    for entry in impact:
        impact_table.add_row(
            entry["collection"],
            str(entry["total_packages"]),
            str(entry["base_packages"]),
            str(entry["remaining_packages"]),
            f"{entry['reduction_percentage']:.1f}%",
        )
    console.print(impact_table)

    # Remaining Packages table — deduplicated across all collections
    seen: set[NormalizedName] = set()
    remaining_rows: list[dict[str, typing.Any]] = []
    for entry in impact:
        for pkg_entry in entry["remaining"]:
            pkg = pkg_entry["package"]
            if pkg not in seen:
                seen.add(pkg)
                remaining_rows.append(pkg_entry)
    remaining_rows.sort(key=lambda x: (-x["collection_count"], x["package"]))

    remaining_table = Table(
        title="Remaining Packages (not in proposed base)",
        box=rich.box.MARKDOWN,
        title_justify="left",
    )
    remaining_table.add_column("Package", justify="left", no_wrap=True)
    remaining_table.add_column("Collections", justify="right", no_wrap=True)
    remaining_table.add_column("Coverage", justify="right", no_wrap=True)
    for pkg_entry in remaining_rows:
        count = pkg_entry["collection_count"]
        remaining_table.add_row(
            pkg_entry["package"],
            f"{count}/{total_collections}",
            f"{(count / total_collections) * 100:.1f}%",
        )
    console.print(remaining_table)

    if base_only_packages:
        base_only_table = Table(
            title="Existing Base Packages (carried forward, not new candidates)",
            box=rich.box.MARKDOWN,
            title_justify="left",
        )
        base_only_table.add_column("Package", justify="left", no_wrap=True)
        for pkg in sorted(base_only_packages):
            base_only_table.add_row(str(pkg))
        console.print(base_only_table)


def _suggest_base_json(
    candidates: list[dict[str, typing.Any]],
    total_collections: int,
    collection_names: list[str],
    min_collections: int,
    base_packages: set[NormalizedName] | None,
    base_graph: str | None,
    total_unique_packages: int,
    impact: list[dict[str, typing.Any]],
    base_only_packages: set[NormalizedName],
) -> None:
    """Display suggest-base results as JSON."""
    output: dict[str, typing.Any] = {
        "metadata": {
            "total_collections": total_collections,
            "total_unique_packages": total_unique_packages,
            "packages_meeting_threshold": len(candidates),
            "collections": sorted(collection_names),
            "min_collections": min_collections,
        },
        "candidates": [],
        "collection_impact": impact,
    }
    if base_graph is not None:
        output["metadata"]["base_graph"] = base_graph

    for entry in candidates:
        pkg = entry["package"]
        count = entry["count"]
        cols = entry["collections"]
        candidate: dict[str, typing.Any] = {
            "package": pkg,
            "collections": cols,
            "collection_count": count,
            "coverage_percentage": round((count / total_collections) * 100, 1),
        }
        if base_packages is not None:
            candidate["in_base"] = pkg in base_packages
        output["candidates"].append(candidate)

    if base_only_packages:
        output["base_only_packages"] = sorted(str(p) for p in base_only_packages)

    json.dump(output, sys.stdout, indent=2)


def _suggest_base_impl(
    collection_graphs: tuple[str, ...],
    base_graph: str | None,
    min_collections: int | None,
    output_format: str,
) -> None:
    """Core implementation for suggest_base, testable without a click context."""
    if len(collection_graphs) < 2:
        raise click.UsageError("At least 2 collection graphs are required")
    if min_collections is None:
        min_collections = max(2, math.ceil(len(collection_graphs) / 2))
    elif min_collections < 2:
        raise click.UsageError("--min-collections must be >= 2")
    if min_collections > len(collection_graphs):
        raise click.UsageError(
            f"--min-collections ({min_collections}) cannot exceed number of graphs ({len(collection_graphs)})"
        )

    # Load each collection, keyed by resolved path to avoid stem collisions
    collections: dict[str, set[NormalizedName]] = {}
    display_names: dict[str, str] = {}
    for path in collection_graphs:
        key = str(pathlib.Path(path).resolve())
        name = _get_collection_name(path)
        pkgs = _get_collection_packages(path)
        if not pkgs:
            logger.warning("Collection %s is empty, skipping", name)
            continue
        collections[key] = pkgs
        display_names[key] = name

    # Load base graph if provided
    base_packages: set[NormalizedName] | None = None
    if base_graph:
        base_packages = _get_collection_packages(base_graph)

    total_unique_packages = len(set().union(*collections.values()))
    candidates = _find_shared_packages(collections, min_collections, display_names)
    total = len(collections)

    candidate_names: set[NormalizedName] = {entry["package"] for entry in candidates}
    # The full proposed base includes existing base packages (all carried forward)
    proposed_base: set[NormalizedName] = (
        candidate_names | base_packages if base_packages else candidate_names
    )
    # Packages carried from the existing base that are not new candidates
    base_only_packages: set[NormalizedName] = (
        base_packages - candidate_names if base_packages else set()
    )
    impact = _compute_collection_impact(collections, proposed_base, display_names)

    if output_format == "json":
        _suggest_base_json(
            candidates,
            total,
            list(display_names.values()),
            min_collections,
            base_packages,
            base_graph,
            total_unique_packages,
            impact,
            base_only_packages,
        )
    else:
        _suggest_base_table(
            candidates,
            total,
            list(display_names.values()),
            min_collections,
            base_packages,
            total_unique_packages,
            impact,
            base_only_packages,
        )


@graph.command()
@click.option(
    "--base",
    "base_graph",
    type=str,
    default=None,
    help="Existing base collection graph to enhance",
)
@click.option(
    "--min-collections",
    type=int,
    default=None,
    help="Minimum collections a package must appear in (default: 50% of provided collections)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format (default: table)",
)
@click.argument("collection_graphs", nargs=-1, required=True)
@click.pass_obj
def suggest_base(
    wkctx: context.WorkContext,
    collection_graphs: tuple[str, ...],
    base_graph: str | None,
    min_collections: int | None,
    output_format: str,
) -> None:
    """Suggest packages for a shared base collection.

    Analyzes COLLECTION_GRAPHS (2 or more graph files) to identify packages
    appearing across multiple collections. These are candidates for factoring
    into a base collection built once and reused.
    """
    _suggest_base_impl(collection_graphs, base_graph, min_collections, output_format)
