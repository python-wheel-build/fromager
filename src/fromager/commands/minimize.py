import logging
import pathlib
import sys
from collections.abc import Generator

import click
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from fromager import clickext, context, requirements_file
from fromager.dependency_graph import DependencyGraph

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    help="Output file for minimized requirements (default: stdout)",
)
@click.argument(
    "requirements-filename",
    type=clickext.ClickPath(exists=True),
)
@click.argument(
    "graph-filename",
    type=clickext.ClickPath(exists=True),
)
@click.pass_obj
def minimize(
    wkctx: context.WorkContext,
    requirements_filename: pathlib.Path,
    graph_filename: pathlib.Path,
    output: pathlib.Path | None,
) -> None:
    """
    Minimize a requirements.txt file by removing packages that would be
    automatically included as dependencies of other packages.

    Takes a requirements.txt file and a graph file as input and produces
    a minimized requirements.txt file that removes redundant dependencies.
    This helps avoid conflicts and reduces the overall graph size.
    """

    # Parse the input requirements file
    try:
        requirements: list[Requirement] = []
        for line in requirements_file.parse_requirements_file(requirements_filename):
            requirements.append(Requirement(line))
    except Exception as e:
        logger.error(f"Failed to parse requirements file {requirements_filename}: {e}")
        raise

    if not requirements:
        logger.error("No valid requirements found in requirements file")
        sys.exit(1)

    # Load the dependency graph
    try:
        graph = DependencyGraph.from_file(graph_filename)
    except Exception as e:
        logger.error(f"Failed to load graph file {graph_filename}: {e}")
        raise

    # Find the minimal set of requirements
    minimal_requirements = list(_minimize_requirements(requirements, graph))

    # Write output
    output_lines = [str(req) for req in minimal_requirements]

    if output:
        try:
            with open(output, "w") as f:
                for line in output_lines:
                    f.write(line + "\n")
            logger.info(f"Minimized requirements written to {output}")
        except Exception as e:
            logger.error(f"Failed to write output file {output}: {e}")
            raise
    else:
        for line in output_lines:
            print(line)

    # Report statistics
    original_count = len(requirements)
    minimal_count = len(minimal_requirements)
    removed_count = original_count - minimal_count

    logger.info(f"Original requirements: {original_count}")
    logger.info(f"Minimized requirements: {minimal_count}")
    logger.info(f"Removed dependencies: {removed_count}")
    logger.info(f"Reduction: {removed_count / original_count * 100:.2f}%")


def _minimize_requirements(
    requirements: list[Requirement], graph: DependencyGraph
) -> Generator[Requirement, None, None]:
    """
    Minimize a list of requirements by removing those that are dependencies
    of other nodes in the graph AND would resolve to the same version.
    """

    for req in requirements:
        # Skip requirements that use exact version specification (==)
        has_exact_version = any(spec.operator == "==" for spec in req.specifier)
        if has_exact_version:
            logger.debug(f"Keeping {req} (uses exact version specification)")
            yield req
            continue

        canonical_name = canonicalize_name(req.name)
        should_keep = True

        # Check if this requirement would be satisfied by any dependency
        # of other nodes in the graph (excluding toplevel)
        for node in graph.get_install_dependencies():
            # Skip the root/toplevel node
            if node.key == "":
                continue

            # Check all outgoing install/toplevel edges from this node
            for edge in node.children:
                if not edge.req_type.is_install_requirement:
                    continue
                dep_name = canonicalize_name(edge.destination_node.canonicalized_name)
                if dep_name != canonical_name:
                    continue
                dep_version = edge.destination_node.version

                # Only mark as removable if the requirement's specifier
                # would be satisfied by the version that appears as a dependency
                if req.specifier.contains(dep_version, prereleases=True):
                    logger.debug(
                        f"Candidate for removal: {req} "
                        f"(satisfied by dependency version {dep_version})"
                    )
                    should_keep = False
                    break

            if not should_keep:
                break

        if should_keep:
            yield req
        else:
            logger.debug(
                f"Removing {req} as it would be satisfied by dependencies of other nodes"
            )
