import logging
import pathlib

import click
import rich
import rich.box
from packaging.requirements import Requirement
from rich.table import Table

from fromager import (
    context,
    requirements_file,
)
from fromager.dependency_graph import DependencyGraph

logger = logging.getLogger(__name__)


@click.command()
@click.argument("req_file", type=click.Path(exists=True, path_type=pathlib.Path))
@click.argument("graph_file", type=click.Path(exists=True, path_type=pathlib.Path))
@click.pass_obj
def stats(
    wkctx: context.WorkContext,
    req_file: pathlib.Path,
    graph_file: pathlib.Path,
) -> None:
    """Show statistics about packages in a build

    REQ_FILE is the requirements.txt file used for the build

    GRAPH_FILE is the fromager graph.json file produced by the build

    Shows a table with various statistics about the packages including
    counts of unique packages, constraints, configurations, prebuilt packages,
    patches, and build plugins.
    """

    # Read requirements.txt file
    requirements_count = 0
    try:
        requirement_lines = list(requirements_file.parse_requirements_file(req_file))
        requirements_count = len(requirement_lines)
    except Exception as e:
        logger.error(f"Failed to read requirements file {req_file}: {e}")
        return

    # Read graph.json file
    try:
        graph = DependencyGraph.from_file(graph_file)
    except Exception as e:
        logger.error(f"Failed to read graph file {graph_file}: {e}")
        return

    # Extract unique package names from graph
    unique_packages: set[str] = set()
    prebuilt_packages: set[str] = set()

    for node in graph.get_all_nodes():
        # Skip the root node which has empty name
        if node.canonicalized_name:
            unique_packages.add(node.canonicalized_name)
            if node.pre_built:
                prebuilt_packages.add(node.canonicalized_name)

    # Analyze package configurations
    constrained_packages: set[str] = set()
    configured_packages: set[str] = set()
    patched_packages: set[str] = set()
    plugin_packages: set[str] = set()

    for package_name in unique_packages:
        try:
            req = Requirement(package_name)
            pbi = wkctx.package_build_info(req)

            # Check if package has constraints
            try:
                constraint = wkctx.constraints.get_constraint(package_name)
                if constraint is not None:
                    constrained_packages.add(package_name)
            except Exception:
                pass

            # Check if package has any fromager configuration
            try:
                # Use the has_config attribute from PackageSettings which indicates
                # whether the package has a configuration file
                ps = wkctx.settings.package_setting(package_name)
                if ps.has_config:
                    configured_packages.add(package_name)
            except Exception:
                pass

            # Check if package has patches
            try:
                all_patches = pbi.get_all_patches()
                if all_patches:  # Check if the patch map is not empty
                    patched_packages.add(package_name)
            except Exception:
                pass

            # Check if package has build plugins
            try:
                if pbi.plugin is not None:
                    plugin_packages.add(package_name)
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Could not analyze package {package_name}: {e}")
            continue

    # Create stats table
    table = Table(title="Build Statistics", box=rich.box.MARKDOWN, title_justify="left")
    table.add_column("Metric", justify="left", no_wrap=True)
    table.add_column("Count", justify="right", no_wrap=True)
    table.add_column("Percentage", justify="right", no_wrap=True)

    total_packages = len(unique_packages)

    def format_percentage(count: int, total: int) -> str:
        if total == 0:
            return "0.0%"
        return f"{(count / total) * 100:.1f}%"

    table.add_row("Requirements in requirements.txt", str(requirements_count), "-")
    table.add_row("Constraints defined", str(len(list(wkctx.constraints))), "-")
    table.add_row("Unique packages in build", str(total_packages), "100.0%")
    table.add_row(
        "Packages in the build with constraints",
        str(len(constrained_packages)),
        format_percentage(len(constrained_packages), total_packages),
    )
    table.add_row(
        "Pre-built packages",
        str(len(prebuilt_packages)),
        format_percentage(len(prebuilt_packages), total_packages),
    )
    table.add_row(
        "Packages with any fromager config",
        str(len(configured_packages)),
        format_percentage(len(configured_packages), total_packages),
    )
    table.add_row(
        "Packages with patches",
        str(len(patched_packages)),
        format_percentage(len(patched_packages), total_packages),
    )
    table.add_row(
        "Packages with build plugins",
        str(len(plugin_packages)),
        format_percentage(len(plugin_packages), total_packages),
    )

    # Display the table
    console = rich.get_console()
    console.print(table)
