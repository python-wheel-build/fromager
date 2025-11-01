import logging
import time
import typing
from datetime import timedelta

import click
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from fromager.dependency_graph import DependencyNode

from .. import (
    bootstrapper,
    context,
    dependency_graph,
    metrics,
    progress,
    requirements_file,
    resolver,
    server,
)
from ..log import requirement_ctxvar
from ..requirements_file import RequirementType
from .build import build_parallel
from .graph import find_why, show_explain_duplicates

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
                f"ignoring {requirements_file.RequirementType.TOP_LEVEL} dependency {req} because of its marker expression"
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
@click.option(
    "--sdist-only/--full-build",
    "sdist_only",
    default=False,
    help=(
        "--sdist-only (fast mode) does not build missing wheels unless they "
        "are build requirements. --full-build (default) builds all missing "
        "wheels."
    ),
)
@click.option(
    "--skip-constraints",
    "skip_constraints",
    is_flag=True,
    default=False,
    help="Skip generating constraints.txt file to allow building collections with conflicting versions",
)
@click.option(
    "--test-mode",
    "test_mode",
    is_flag=True,
    default=False,
    help="Test mode: mark failed packages as pre-built and continue, report failures at end",
)
@click.argument("toplevel", nargs=-1)
@click.pass_obj
def bootstrap(
    wkctx: context.WorkContext,
    requirements_files: list[str],
    previous_bootstrap_file: str | None,
    cache_wheel_server_url: str | None,
    sdist_only: bool,
    skip_constraints: bool,
    test_mode: bool,
    toplevel: list[str],
) -> None:
    """Compute and build the dependencies of a set of requirements recursively

    TOPLEVEL is a requirements specification, including a package name
    and optional version constraints.

    """
    logger.info(f"cache wheel server url: {cache_wheel_server_url}")

    if test_mode:
        logger.info(
            "test mode enabled: will mark failed packages as pre-built and continue"
        )

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

    if sdist_only:
        logger.info("sdist-only (fast mode), getting metadata from sdists")
    else:
        logger.info("build all missing wheels")

    pre_built = wkctx.settings.list_pre_built()
    if pre_built:
        logger.info("treating %s as pre-built wheels", sorted(pre_built))

    server.start_wheel_server(wkctx)

    with progress.progress_context(total=len(to_build * 2)) as progressbar:
        bt = bootstrapper.Bootstrapper(
            wkctx,
            progressbar,
            prev_graph,
            cache_wheel_server_url,
            sdist_only=sdist_only,
            test_mode=test_mode,
        )

        # we need to resolve all the top level dependencies before we start bootstrapping.
        # this is to ensure that if we are using an older bootstrap to resolve packages
        # we are able to upgrade a package anywhere in the dependency tree if it is mentioned
        # in the toplevel without having to fall back to history
        logger.info("resolving top-level dependencies before building")
        for req in to_build:
            token = requirement_ctxvar.set(req)
            pbi = wkctx.package_build_info(req)
            if pbi.pre_built:
                source_url, version = bt.resolve_version(
                    req=req,
                    req_type=RequirementType.TOP_LEVEL,
                )
            else:
                source_url, version = bt.resolve_version(
                    req=req,
                    req_type=RequirementType.TOP_LEVEL,
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
                constraint=wkctx.constraints.get_constraint(req.name),
            )
            requirement_ctxvar.reset(token)

        for req in to_build:
            token = requirement_ctxvar.set(req)
            try:
                bt.bootstrap(req, requirements_file.RequirementType.TOP_LEVEL)
                progressbar.update()
                if test_mode:
                    logger.info("Successfully processed: %s", req)
            except Exception as err:
                if test_mode:
                    # Test mode: log error but continue processing
                    logger.error(
                        "test mode: failed to process %s: %s",
                        req,
                        err,
                        exc_info=True,  # Full traceback to debug log
                    )
                    progressbar.update()  # Update progress even on failure
                else:
                    # Normal mode: re-raise the exception (fail-fast)
                    raise
            finally:
                requirement_ctxvar.reset(token)

    constraints_filename = wkctx.work_dir / "constraints.txt"
    if skip_constraints:
        logger.info("skipping constraints.txt generation as requested")
    else:
        logger.info(f"writing installation dependencies to {constraints_filename}")
        with open(constraints_filename, "w") as f:
            if not write_constraints_file(graph=wkctx.dependency_graph, output=f):
                raise ValueError(
                    f"Could not produce a pip compatible constraints file. Please review {constraints_filename} for more details"
                )

    logger.debug("match_py_req LRU cache: %r", resolver.match_py_req.cache_info())

    # Test mode summary reporting
    if test_mode:
        if bt.failed_packages:
            # Use repository's logging pattern for error reporting
            logger.error("test mode: the following packages failed to build:")
            for package in sorted(bt.failed_packages):
                logger.error("  - %s", package)
            logger.error(
                "test mode: %d package(s) failed to build", len(bt.failed_packages)
            )
            # Follow repository's error exit pattern like __main__.py and lint.py
            raise SystemExit(
                f"Test mode completed with {len(bt.failed_packages)} build failures"
            )
        else:
            logger.info("test mode: all packages built successfully")
        metrics.summarize(wkctx, "Test Mode Bootstrapping")
    else:
        metrics.summarize(wkctx, "Bootstrapping")


def write_constraints_file(
    graph: dependency_graph.DependencyGraph,
    output: typing.TextIO,
) -> bool:
    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts: dict[NormalizedName, list[DependencyNode]] = (
        graph.get_install_dependency_versions()
    )
    ret = True

    # Map for already resolved versions for a given dependency Eg: {"a": "0.4"}
    resolved: dict[NormalizedName, Version] = {}

    # List of unresolved dependencies
    unresolved_dependencies: list[tuple[NormalizedName, list[DependencyNode]]] = sorted(
        conflicts.items()
    )

    dep_name: NormalizedName

    # Loop over dependencies and resolve dependencies with single version first. This will shrink the unresolved_dependencies to begin with.
    for dep_name, nodes in unresolved_dependencies[:]:
        versions: list[Version] = [node.version for node in nodes]
        if len(versions) == 0:
            # This should never happen.
            raise ValueError(f"No versions of {dep_name} supported")

        if len(versions) == 1:
            logger.debug(
                "resolving %s to %s",
                dep_name,
                versions[0],
            )
            # This is going to be the situation for most dependencies, where we
            # only have one version.
            resolved[dep_name] = versions[0]
            # Remove from unresolved dependencies list
            unresolved_dependencies.remove((dep_name, nodes))
    multiple_versions: dict[NormalizedName, list[DependencyNode]] = dict(
        unresolved_dependencies
    )

    # Below this point we have built multiple versions of the same thing, so
    # we need to try to determine if any one of those versions meets all of
    # the requirements.

    # Flag to see if something is resolved
    resolved_something: bool = True

    # Track packages that cannot be resolved due to conflicting constraints
    conflicting_deps: set[NormalizedName] = set()

    # Outer while loop to resolve remaining dependencies with multiple versions
    while unresolved_dependencies and resolved_something:
        logger.debug(
            "starting to resolve %s",
            [dep_name for dep_name, _ in unresolved_dependencies],
        )
        resolved_something = False
        # Make copy of the original list and loop over unresolved dependencies
        for dep_name, nodes in unresolved_dependencies[:]:
            # Skip packages we've already determined are unresolvable
            if dep_name in conflicting_deps:
                continue
            # Track which versions can be used by which parent requirement.
            usable_versions: dict[Version, list[Version]] = {}
            # Track how many total users of a requirement (by name) there are so we
            # can tell later if any version can be used by all of them.
            user_counter: int = 0
            # Which parent requirements can use which versions of the dependency we
            # are working on?
            dep_versions: list[Version] = [node.version for node in nodes]

            # Loop over the nodes list
            for node in nodes:
                parent_edges: list[dependency_graph.DependencyEdge] = (
                    node.get_incoming_install_edges()
                )
                if not parent_edges:
                    # This is a top level dependency, so we should ensure that the
                    # resolved version is considered as a candidate.
                    usable_versions.setdefault(node.version, []).append(node.version)

                # Loop over parent_edges list
                for parent_edge in parent_edges:
                    parent_name: NormalizedName = (
                        parent_edge.destination_node.canonicalized_name
                    )
                    # Condition to select the right version.
                    # We check whether parent_name is already in resolved dict and the version associated with that
                    # is not the version of the destination node
                    if (
                        parent_name in resolved
                        and resolved[parent_name]
                        != parent_edge.destination_node.version
                    ):
                        continue

                    # NOTE: We don't re-evaluate markers here because if a dependency
                    # is in the graph, it means the markers were already properly
                    # evaluated during graph construction with the correct extras context.
                    # Re-evaluating markers without that context would be incorrect.
                    # Loop to find the usable versions
                    for matching_version in parent_edge.req.specifier.filter(  # type: ignore
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
            for v, users in reversed(sorted(usable_versions.items())):  # type: ignore
                logger.debug(
                    "considering %s for %s, %d of %d consumers",
                    v,
                    dep_name,
                    len(users),
                    user_counter,
                )
                if len(users) != user_counter:
                    logger.debug(
                        "%s: version %s is useable by %d of %d consumers, skipping it",
                        dep_name,
                        v,
                        len(users),
                        user_counter,
                    )
                    continue
                version_strs: list[str] = [
                    str(v) for v in reversed(sorted(dep_versions))
                ]
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
            else:
                # No version could satisfy all users - mark as unresolvable
                conflicting_deps.add(dep_name)
                logger.debug(
                    "%s: marking as unresolvable - no version satisfies all %d users",
                    dep_name,
                    user_counter,
                )

    # Write resolved versions to constraints file
    for dep_name, resolved_version in sorted(resolved.items()):  # type: ignore
        if dep_name in multiple_versions:
            version_strs = [
                str(node.version)
                for node in sorted(multiple_versions[dep_name], key=lambda n: n.version)
            ]
            output.write(
                f"# NOTE: fromager selected {dep_name}=={resolved_version} from: {version_strs}\n"
            )
        output.write(f"{dep_name}=={resolved_version}\n")

    # Check if there are any unresolved dependencies (conflicts)
    if unresolved_dependencies or conflicting_deps:
        # We have conflicts - don't write anything to constraints file
        # and return False to indicate failure
        ret = False

        # Compute all conflicting packages (avoid duplicates)
        all_conflicting_deps: set[NormalizedName] = (
            set(dep_name for dep_name, _ in unresolved_dependencies) | conflicting_deps
        )

        # Report all conflicting packages
        for dep_name in sorted(all_conflicting_deps):
            logger.error("%s: no single version meets all requirements", dep_name)

        # Show detailed information about why these packages conflict
        for dep_name in all_conflicting_deps:
            for node in graph.get_nodes_by_name(dep_name):
                find_why(
                    graph=graph,
                    node=node,
                    max_depth=-1,
                    depth=0,
                    req_type=[],
                )

        # Show the report that explains which rules match which versions
        # of any duplicates.
        print("\nSome packages have multiple version based on different requirements:")
        show_explain_duplicates(graph)

        return ret

    return ret


bootstrap._fromager_show_build_settings = True  # type: ignore


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
@click.option(
    "--skip-constraints",
    "skip_constraints",
    is_flag=True,
    default=False,
    help="Skip generating constraints.txt file to allow building collections with conflicting versions",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="rebuild wheels even if they have already been built",
)
@click.option(
    "-m",
    "--max-workers",
    type=int,
    default=None,
    help="maximum number of parallel workers to run (default: unlimited)",
)
@click.option(
    "--test-mode",
    "test_mode",
    is_flag=True,
    default=False,
    help="Test mode: mark failed packages as pre-built and continue, report failures at end",
)
@click.argument("toplevel", nargs=-1)
@click.pass_obj
@click.pass_context
def bootstrap_parallel(
    ctx: click.Context,
    wkctx: context.WorkContext,
    *,
    requirements_files: list[str],
    previous_bootstrap_file: str | None,
    cache_wheel_server_url: str | None,
    skip_constraints: bool,
    force: bool,
    max_workers: int | None,
    test_mode: bool,
    toplevel: list[str],
) -> None:
    """Bootstrap and build-parallel

    Bootstraps all dependencies in sdist-only mode, then builds the
    remaining wheels in parallel. The bootstrap step downloads sdists
    and builds build-time dependency in serial. The build-parallel step
    builds the remaining wheels in parallel.
    """
    # Do not remove build environments in bootstrap phase to speed up the
    # parallel build phase.
    logger.info("keep build env for build-parallel phase")
    wkctx.cleanup_buildenv = False

    start = time.perf_counter()
    logger.info("*** starting bootstrap in sdist-only mode ***")
    ctx.invoke(
        bootstrap,
        requirements_files=requirements_files,
        previous_bootstrap_file=previous_bootstrap_file,
        cache_wheel_server_url=cache_wheel_server_url,
        sdist_only=True,
        skip_constraints=skip_constraints,
        test_mode=test_mode,
        toplevel=toplevel,
    )

    # statistics
    wheels = sorted(f.name for f in wkctx.wheels_downloads.glob("*.whl"))
    sdists = sorted(f.name for f in wkctx.sdists_downloads.glob("*.tar.gz"))
    logger.debug("wheels: %s", ", ".join(wheels))
    logger.debug("sdists: %s", ", ".join(sdists))
    logger.info("bootstrap: %i wheels, %i sdists", len(wheels), len(sdists))
    logger.info(
        "*** finished bootstrap in %s ***\n",
        timedelta(seconds=round(time.perf_counter() - start, 0)),
    )

    # reset dependency graph
    wkctx.dependency_graph.clear()

    # cleanup build envs in build-parallel step
    wkctx.cleanup_buildenv = wkctx.cleanup

    start_build = time.perf_counter()
    logger.info("*** starting build-parallel with %s ***", wkctx.graph_file)
    ctx.invoke(
        build_parallel,
        cache_wheel_server_url=cache_wheel_server_url,
        max_workers=max_workers,
        force=force,
        graph_file=wkctx.graph_file,
    )
    logger.info(
        "*** finished build-parallel in %s, total %s ***\n",
        timedelta(seconds=round(time.perf_counter() - start_build, 0)),
        timedelta(seconds=round(time.perf_counter() - start, 0)),
    )
