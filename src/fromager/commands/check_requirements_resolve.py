import logging
import sys

import click
from packaging.requirements import InvalidRequirement, Requirement

from fromager import requirements_file, resolver, sources, wheels
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType

logger = logging.getLogger(__name__)


@click.command()
@click.argument(
    "input_files_path", nargs=-1, required=True, type=click.Path(exists=False)
)
@click.pass_obj
def check_requirements_resolve(wkctx: WorkContext, input_files_path: list[str]) -> None:
    """
    Check that top-level requirements resolve.
    This command takes a single wildcard path string for constraints.txt and requirements.txt.
    It checks the top-level entries of these files resolve and reports issues if found.
    """
    if not input_files_path:
        logger.error("no constraints.txt or requirements.txt found in given paths")
        sys.exit(1)

    failure = False
    for path in input_files_path:
        for line in requirements_file.parse_requirements_file(path):
            try:
                req = Requirement(line)
            except InvalidRequirement as err:
                logger.error(f"{path}: invalid requirement {line!r}: {err}")
                failure = True
                continue

            pbi = wkctx.package_build_info(req)
            try:
                if pbi.pre_built:
                    servers = wheels.get_wheel_server_urls(wkctx, req)
                    url, version = wheels.resolve_prebuilt_wheel(
                        ctx=wkctx, req=req, wheel_server_urls=servers
                    )
                else:
                    url, version = sources.resolve_source(
                        ctx=wkctx,
                        req=req,
                        req_type=RequirementType.TOP_LEVEL,
                        sdist_server_url=resolver.PYPI_SERVER_URL,
                    )
                logger.info(f"{req} resolves to {version}")
            except Exception as err:
                logger.error(f"{path}: {req}: resolution failed: {err}")
                failure = True

    if failure:
        sys.exit(1)
