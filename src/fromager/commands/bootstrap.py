import logging
import pathlib
import typing

import click
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from .. import clickext, context, progress, requirements_file, sdist, server

# Map child_name==child_version to list of (parent_name==parent_version, Requirement)
ReverseRequirements = dict[str, list[tuple[str, Requirement]]]

logger = logging.getLogger(__name__)


def _get_requirements_from_args(
    toplevel: typing.Iterable[str],
    req_files: typing.Iterable[pathlib.Path],
) -> typing.Sequence[tuple[str, str]]:
    to_build: list[tuple[str, str]] = []
    to_build.extend(("toplevel", t) for t in toplevel)
    for filename in req_files:
        to_build.extend(
            (str(filename), req)
            for req in requirements_file.parse_requirements_file(filename)
        )
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
@click.argument("toplevel", nargs=-1)
@click.pass_obj
def bootstrap(
    wkctx: context.WorkContext,
    requirements_files: list[pathlib.Path],
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

    pre_built = wkctx.settings.pre_built(wkctx.variant)
    if pre_built:
        logger.info("treating %s as pre-built wheels", list(sorted(pre_built)))

    server.start_wheel_server(wkctx)

    with progress.progress_context(total=len(to_build)) as progressbar:
        for origin, dep in to_build:
            sdist.handle_requirement(
                wkctx, Requirement(dep), req_type=origin, progressbar=progressbar
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
        write_constraints_file(graph=wkctx.all_edges, output=f)


def write_constraints_file(
    graph: context.BuildRequirements,
    output: typing.TextIO,
) -> None:
    reverse_graph: ReverseRequirements = reverse_dependency_graph(graph)

    # The installation dependencies are (name, version) pairs, and there may be
    # duplicates because multiple packages depend on the same version of another
    # package. Eliminate those duplicates using a set, so we can more easily
    # find cases where we depend on two different versions of the same thing.
    install_constraints = set(
        (name, version)
        for name, version, _ in installation_dependencies(
            all_edges=graph,
            name=context.ROOT_BUILD_REQUIREMENT,
            version=None,
        )
    )

    # Look for potential conflicts by tracking how many different versions of
    # each package are needed.
    conflicts: dict[NormalizedName, list[Version]] = {}
    for dep_name, dep_version in install_constraints:
        conflicts.setdefault(dep_name, []).append(dep_version)

    for dep_name, versions in sorted(conflicts.items()):
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
        for dep_version in versions:
            key = f"{dep_name}=={dep_version}"
            parent_info = reverse_graph.get(key, [])
            user_counter += len(parent_info)
            for parent_version, req in parent_info:
                match_versions = [str(v) for v in req.specifier.filter(versions)]
                for mv in match_versions:
                    usable_versions.setdefault(mv, []).append(parent_version)

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


def reverse_dependency_graph(
    graph: context.BuildRequirements,
) -> ReverseRequirements:
    # The graph shows parent->child edges. We need to look up the parent from
    # the child, so build a reverse lookup table.
    reverse_graph: ReverseRequirements = {}
    for parent, children in graph.items():
        parent_name, _, parent_version = parent.partition("==")
        for (
            req_type,
            req_name,
            req_version,
            req,
        ) in children:
            if req_type != "install":
                continue
            key = f"{req_name}=={req_version}"
            reverse_graph.setdefault(key, []).append((parent, req))
    return reverse_graph


def installation_dependencies(
    all_edges: context.BuildRequirements,
    name: NormalizedName,
    version: Version | None,
) -> typing.Iterable[tuple[NormalizedName, Version, Requirement]]:
    # If there is a version, the keys of all_edges will be a str of package_name==package_version. If there is no version, the key is only the name.
    if not version:
        lookup_key = str(name)
    else:
        lookup_key = f"{name}=={version}"
    for req_type, dep_name, dep_version, dep_req in all_edges.get(lookup_key, []):
        if req_type != "install":
            continue
        yield (dep_name, dep_version, dep_req)
        yield from installation_dependencies(
            all_edges=all_edges,
            name=dep_name,
            version=dep_version,
        )
