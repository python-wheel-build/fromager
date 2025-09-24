import logging
import pathlib
import sys

import click
from packaging.requirements import InvalidRequirement, Requirement

from fromager import bootstrapper, context, progress, requirements_file
from fromager.log import requirement_ctxvar
from fromager.requirements_file import RequirementType

logger = logging.getLogger(__name__)


@click.command()
@click.argument(
    "input_files_path",
    nargs=-1,
    required=True,
    type=click.Path(exists=False, path_type=pathlib.Path),
)
@click.pass_obj
def lint_requirements(
    wkctx: context.WorkContext, input_files_path: list[pathlib.Path]
) -> None:
    """
    Command to lint the constraints.txt and requirements.txt files
    This command takes a single wildcard path string for constraints.txt and requirements.txt.
    It checks the formatting of these files and reports issues if found. Files with names that
    end with constraints.txt (e.g. constraints.txt, global-constraints.txt, etc.) are not allowed
    to contain extra dependencies. Additionally, it resolves valid input requirements to ensure
    we can find a matching version of each package.
    """

    if len(input_files_path) == 0:
        logger.error("no constraints.txt or requirements.txt found in given paths")
        sys.exit(1)

    flag = True

    # Create bootstrapper for requirement resolution
    bt = bootstrapper.Bootstrapper(
        ctx=wkctx,
        progressbar=progress.Progressbar(None),
        prev_graph=None,
        cache_wheel_server_url=None,
        sdist_only=True,
    )

    for path in input_files_path:
        parsed_lines = requirements_file.parse_requirements_file(path)
        unique_entries: dict[str, Requirement] = {}
        for line in parsed_lines:
            try:
                requirement = Requirement(line)
                if requirement.name in unique_entries:
                    raise InvalidRequirement(
                        f"Duplicate entry, first found: {unique_entries[requirement.name]}"
                    )
                unique_entries[requirement.name] = requirement
                if requirement.extras and path.name.endswith("constraints.txt"):
                    raise InvalidRequirement(
                        "Constraints files cannot contain extra dependencies"
                    )

                # Resolve the requirement to ensure it can be found
                # Skip resolution for constraints files as they should only specify versions
                if not path.name.endswith("constraints.txt"):
                    token = requirement_ctxvar.set(requirement)
                    try:
                        _, version = bt.resolve_version(
                            req=requirement,
                            req_type=RequirementType.TOP_LEVEL,
                        )
                        logger.info(f"{requirement} resolves to {version}")
                    except Exception as resolve_err:
                        logger.error(
                            f"{path}: {line}: Failed to resolve requirement: {resolve_err}"
                        )
                        flag = False
                    finally:
                        requirement_ctxvar.reset(token)
            except InvalidRequirement as err:
                logger.error(f"{path}: {line}: {err}")
                flag = False

    if not flag:
        sys.exit(1)
