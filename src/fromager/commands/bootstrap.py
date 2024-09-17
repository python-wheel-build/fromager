import logging
import pathlib
import typing

import click
from packaging.requirements import Requirement

from .. import (
    clickext,
    context,
    dependency_graph,
    progress,
    requirements_file,
    resolver,
    sdist,
    server,
    sources,
    wheels,
)

# Map child_name==child_version to list of (parent_name==parent_version, Requirement)
ReverseRequirements = dict[str, list[tuple[str, Requirement]]]

logger = logging.getLogger(__name__)


def _get_requirements_from_args(
    toplevel: typing.Iterable[str],
    req_files: typing.Iterable[pathlib.Path],
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
    type=clickext.ClickPath(),
    help="pip requirements file",
)
@click.option(
    "-p",
    "--previous-bootstrap-file",
    "previous_bootstrap_file",
    type=clickext.ClickPath(),
    help="graph file produced from a previous bootstrap",
)
@click.argument("toplevel", nargs=-1)
@click.pass_obj
def bootstrap(
    wkctx: context.WorkContext,
    requirements_files: list[pathlib.Path],
    previous_bootstrap_file: pathlib.Path | None,
    toplevel: list[str],
) -> None:
    """Compute and build the dependencies of a set of requirements recursively

    TOPLEVEL is a requirements specification, including a package name
    and optional version constraints.

    """
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
            source_url, version = wheels.resolve_prebuilt_wheel(wkctx, req, servers)
        else:
            source_url, version = sources.resolve_source(
                wkctx, req, resolver.PYPI_SERVER_URL
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
        for req in to_build:
            sdist.handle_requirement(
                wkctx,
                req,
                req_type=requirements_file.RequirementType.TOP_LEVEL,
                progressbar=progressbar,
                prev_graph=prev_graph,
            )
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
    with open(wkctx.work_dir / "constraints.txt", "w") as f:
        write_constraints_file(graph=wkctx.dependency_graph, output=f)


def write_constraints_file(
    graph: dependency_graph.DependencyGraph,
    output: typing.TextIO,
) -> None:
    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts = graph.get_install_dependency_versions()

    for dep_name, nodes in sorted(conflicts.items()):
        versions = [node.version for node in nodes]
        if len(versions) == 0:
            # This should never happen.
            raise ValueError(f"No versions of {dep_name} supported")

        if len(versions) == 1:
            # This is going to be the situation for most dependencies, where we
            # only have one version.
            output.write(f"{dep_name}=={versions[0]}\n")
            continue

        # Below this point we have built multiple versions of the same thing, so
        # we need to try to determine if any one of those versions meets all of
        # the requirements.
        logger.debug("%s: found multiple versions in install requirements", dep_name)

        # Track which versions can be used by which parent requirement.
        usable_versions: dict[str, list[str]] = {}
        # Track how many total users of a requirement (by name) there are so we
        # can tell later if any version can be used by all of them.
        user_counter = 0

        # Which parent requirements can use which versions of the dependency we
        # are working on?
        for node in nodes:
            parent_edges = node.get_incoming_install_edges()
            user_counter += len(parent_edges)
            for parent_edge in parent_edges:
                for matching_version in parent_edge.req.specifier.filter(versions):
                    usable_versions.setdefault(str(matching_version), []).append(
                        str(parent_edge.destination_node.version)
                    )

        # Look for one version that can be used by all the parent dependencies
        # and output that if we find it. Otherwise, include a warning and report
        # all versions so a human reading the file can make their own decision
        # about how to resolve the conflict.
        for v, users in usable_versions.items():
            if len(users) == user_counter:
                version_strs = [str(v) for v in sorted(versions)]
                output.write(
                    f"# NOTE: fromager selected {dep_name}=={v} from: {version_strs}\n"
                )
                logging.debug(
                    "%s: selecting %s from multiple candidates %s",
                    dep_name,
                    v,
                    version_strs,
                )
                output.write(f"{dep_name}=={v}\n")
                break
        else:
            # No single version could be used, so go ahead and print all the
            # versions with a warning message.
            output.write(
                f"# ERROR: no single version of {dep_name} met all requirements\n"
            )
            logging.error("%s: no single version meets all requirements", dep_name)
            for dv in sorted(versions):
                output.write(f"{dep_name}=={dv}\n")
