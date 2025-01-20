import logging
import typing

import click
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from .. import (
    bootstrapper,
    context,
    dependency_graph,
    metrics,
    progress,
    requirements_file,
    resolver,
    server,
    sources,
    wheels,
)
from .graph import find_why

# Map child_name==child_version to list of (parent_name==parent_version, Requirement)
ReverseRequirements = dict[str, list[tuple[str, Requirement]]]

logger = logging.getLogger(__name__)


def _get_requirements_from_args(
    toplevel: typing.Iterable[str],
    req_files: typing.Iterable[str],
) -> list[Requirement]:
    parsed_req: list[str] = []
    parsed_req.extend(toplevel)
    for filename in req_files:
        parsed_req.extend(requirements_file.parse_requirements_file(filename))
    to_build: list[Requirement] = []
    for dep in parsed_req:
        req = Requirement(dep)
        # If we're given a requirements file as input, we might be iterating over a
        # list of requirements with marker expressions that limit their use to
        # specific platforms or python versions. Evaluate the markers to filter out
        # anything we shouldn't build. Only apply the filter to toplevel
        # requirements (items without a why list leading up to them) because other
        # dependencies are already filtered based on their markers in the context of
        # their parent, so they include values like the parent's extras settings.
        if not requirements_file.evaluate_marker(req, req):
            logger.info(
                f"{req.name}: ignoring {requirements_file.RequirementType.TOP_LEVEL} dependency {req} because of its marker expression"
            )
        else:
            to_build.append(req)
    return to_build


@click.command()
@click.option(
    "-r",
    "--requirements-file",
    "requirements_files",
    multiple=True,
    type=str,
    help="pip requirements file",
)
@click.option(
    "-p",
    "--previous-bootstrap-file",
    "previous_bootstrap_file",
    type=str,
    help="graph file produced from a previous bootstrap",
)
@click.option(
    "-c",
    "--cache-wheel-server-url",
    "cache_wheel_server_url",
    help="url to a wheel server from where fromager can download the wheels that it has built before",
)
@click.argument("toplevel", nargs=-1)
@click.pass_obj
def bootstrap(
    wkctx: context.WorkContext,
    requirements_files: list[str],
    previous_bootstrap_file: str | None,
    cache_wheel_server_url: str | None,
    toplevel: list[str],
) -> None:
    """Compute and build the dependencies of a set of requirements recursively

    TOPLEVEL is a requirements specification, including a package name
    and optional version constraints.

    """
    logger.info(f"cache wheel server url: {cache_wheel_server_url}")
    to_build = _get_requirements_from_args(toplevel, requirements_files)
    if not to_build:
        raise RuntimeError(
            "Pass a requirement specificiation or use -r to pass a requirements file"
        )
    logger.info("bootstrapping %r variant of %s", wkctx.variant, to_build)

    if previous_bootstrap_file:
        logger.info("reading previous bootstrap data from %s", previous_bootstrap_file)
        prev_graph = dependency_graph.DependencyGraph.from_file(previous_bootstrap_file)
    else:
        logger.info("no previous bootstrap data")
        prev_graph = None

    pre_built = wkctx.settings.list_pre_built()
    if pre_built:
        logger.info("treating %s as pre-built wheels", sorted(pre_built))

    server.start_wheel_server(wkctx)

    # we need to resolve all the top level dependencies before we start bootstrapping.
    # this is to ensure that if we are using an older bootstrap to resolve packages
    # we are able to upgrade a package anywhere in the dependency tree if it is mentioned
    # in the toplevel without having to fall back to history
    logger.info("resolving top-level dependencies before building")
    for req in to_build:
        pbi = wkctx.package_build_info(req)
        if pbi.pre_built:
            servers = wheels.get_wheel_server_urls(wkctx, req)
            source_url, version = wheels.resolve_prebuilt_wheel(
                ctx=wkctx,
                req=req,
                wheel_server_urls=servers,
            )
        else:
            source_url, version = sources.resolve_source(
                ctx=wkctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
            )
        logger.info("%s resolves to %s", req, version)
        wkctx.dependency_graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=requirements_file.RequirementType.TOP_LEVEL,
            req=req,
            req_version=version,
            download_url=source_url,
            pre_built=pbi.pre_built,
        )

    with progress.progress_context(total=len(to_build)) as progressbar:
        bt = bootstrapper.Bootstrapper(
            wkctx, progressbar, prev_graph, cache_wheel_server_url
        )

        for req in to_build:
            bt.bootstrap(req, requirements_file.RequirementType.TOP_LEVEL)
            progressbar.update()

    # If we put pre-built wheels in the downloads directory, we should
    # remove them so we can treat that directory as a source of wheels
    # to upload to an index.
    for prebuilt_wheel in wkctx.wheels_prebuilt.glob("*.whl"):
        filename = wkctx.wheels_downloads / prebuilt_wheel.name
        if filename.exists():
            logger.info(
                f"removing prebuilt wheel {prebuilt_wheel.name} from download cache"
            )
            filename.unlink()

    constraints_filename = wkctx.work_dir / "constraints.txt"
    logger.info(f"writing installation dependencies to {constraints_filename}")
    with open(constraints_filename, "w") as f:
        if not write_constraints_file(graph=wkctx.dependency_graph, output=f):
            raise ValueError(
                f"Could not produce a pip compatible constraints file. Please review {constraints_filename} for more details"
            )

    metrics.summarize(wkctx, "Bootstrapping")


def write_constraints_file(
    graph: dependency_graph.DependencyGraph,
    output: typing.TextIO,
) -> bool:
    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts = graph.get_install_dependency_versions()
    ret = True
    conflicting_deps = set()

    # Map for already resolved versions for a given dependency Eg: {"a": "0.4"}
    resolved: dict[NormalizedName, Version] = {}

    # List of unresolved dependencies
    unresolved_dependencies = sorted(conflicts.items())

    dep_name: NormalizedName

    # Loop over dependencies and resolve dependencies with single version first. This will shrink the unresolved_dependencies to begin with.
    for dep_name, nodes in unresolved_dependencies[:]:
        versions = [node.version for node in nodes]
        if len(versions) == 0:
            # This should never happen.
            raise ValueError(f"No versions of {dep_name} supported")

        if len(versions) == 1:
            # This is going to be the situation for most dependencies, where we
            # only have one version.
            resolved[dep_name] = versions[0]
            # Remove from unresolved dependencies list
            unresolved_dependencies.remove((dep_name, nodes))
    multiple_versions = dict(unresolved_dependencies)

    # Below this point we have built multiple versions of the same thing, so
    # we need to try to determine if any one of those versions meets all of
    # the requirements.

    # Flag to see if something is resolved
    resolved_something = True

    # Outer while loop to resolve remaining dependencies with multiple versions
    while unresolved_dependencies and resolved_something:
        resolved_something = False
        # Make copy of the original list and loop over unresolved dependencies
        for dep_name, nodes in unresolved_dependencies[:]:
            # Track which versions can be used by which parent requirement.
            usable_versions: dict[Version, list[Version]] = {}
            # Track how many total users of a requirement (by name) there are so we
            # can tell later if any version can be used by all of them.
            user_counter = 0
            # Which parent requirements can use which versions of the dependency we
            # are working on?
            dep_versions = [node.version for node in nodes]
            # Loop over the nodes list
            for node in nodes:
                parent_edges = node.get_incoming_install_edges()
                # Loop over parent_edges list
                for parent_edge in parent_edges:
                    parent_name = parent_edge.destination_node.canonicalized_name
                    # Condition to select the right version.
                    # We check whether parent_name is already in resolved dict and the version associated with that
                    # is not the version of the destination node
                    if (
                        parent_name in resolved
                        and resolved[parent_name]
                        != parent_edge.destination_node.version
                    ):
                        continue
                    # Loop to find the usable versions
                    for matching_version in parent_edge.req.specifier.filter(
                        dep_versions
                    ):
                        usable_versions.setdefault(matching_version, []).append(
                            parent_edge.destination_node.version
                        )
                    user_counter += 1

            # Look for one version that can be used by all the parent dependencies
            # and output that if we find it. Otherwise, include a warning and report
            # all versions so a human reading the file can make their own decision
            # about how to resolve the conflict.
            for v, users in reversed(sorted(usable_versions.items())):
                if len(users) != user_counter:
                    logger.debug(
                        "%s: version %s is useable by %d of %d consumers, skipping it",
                        dep_name,
                        v,
                        len(users),
                        user_counter,
                    )
                    continue
                version_strs = [str(v) for v in reversed(sorted(dep_versions))]
                logger.debug(
                    "%s: selecting %s from multiple candidates %s",
                    dep_name,
                    v,
                    version_strs,
                )
                resolved[dep_name] = v
                resolved_something = True
                try:
                    unresolved_dependencies.remove((dep_name, nodes))
                except ValueError:
                    logger.debug(
                        "%s: %s not in unresolved dependencies list, ignoring",
                        dep_name,
                        (dep_name, nodes),
                    )
                break

    # Write resolved versions to constraints file
    for dep_name, resolved_version in sorted(resolved.items()):
        if dep_name in multiple_versions:
            version_strs = [
                str(node.version)
                for node in sorted(multiple_versions[dep_name], key=lambda n: n.version)
            ]
            output.write(
                f"# NOTE: fromager selected {dep_name}=={resolved_version} from: {version_strs}\n"
            )
        output.write(f"{dep_name}=={resolved_version}\n")

    # No single version could be used, so go ahead and print all the
    # versions with a warning message
    for dep_name, nodes in unresolved_dependencies:
        ret = False
        logger.error("%s: no single version meets all requirements", dep_name)
        output.write(f"# ERROR: no single version of {dep_name} met all requirements\n")
        conflicting_deps.add(dep_name)
        for node in sorted(nodes, key=lambda n: n.version):
            output.write(f"{dep_name}=={node.version}\n")

    for dep_name in conflicting_deps:
        logger.error("finding why %s was being used", dep_name)
        for node in graph.get_nodes_by_name(dep_name):
            find_why(graph, node, -1, 1, [])

    return ret


bootstrap._fromager_show_build_settings = True  # type: ignore
