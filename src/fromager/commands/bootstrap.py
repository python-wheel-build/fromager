import logging
import pathlib
import typing

import click
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from .. import clickext, context, progress, requirements_file, sdist, server

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
        for name, version in sorted(
            set(
                _installation_dependencies(
                    wkctx.all_edges, context.ROOT_BUILD_REQUIREMENT
                )
            )
        ):
            f.write(f"{name}=={version}\n")


def _installation_dependencies(
    # The keys of all_edges will be either a validate package name or an empty
    # string.
    all_edges: context.BuildRequirements,
    name: NormalizedName,
) -> typing.Iterable[tuple[NormalizedName, Version]]:
    for req_type, dep_name, dep_version in all_edges.get(name, []):
        if req_type != "install":
            continue
        yield (dep_name, dep_version)
        yield from _installation_dependencies(all_edges, dep_name)
