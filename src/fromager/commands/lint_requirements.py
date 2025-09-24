import logging
import pathlib
import sys

import click
from packaging.requirements import InvalidRequirement, Requirement

from fromager import requirements_file

logger = logging.getLogger(__name__)


@click.command()
@click.argument(
    "input_files_path",
    nargs=-1,
    required=True,
    type=click.Path(exists=False, path_type=pathlib.Path),
)
def lint_requirements(input_files_path: list[pathlib.Path]) -> None:
    """
    Command to lint the constraints.txt and requirements.txt files
    This command takes a single wildcard path string for constraints.txt and requirements.txt.
    It checks the formatting of these files and reports issues if found. Files with names that
    end with constraints.txt (e.g. constraints.txt, global-constraints.txt, etc.) are not allowed
    to contain extra dependencies.
    """

    if len(input_files_path) == 0:
        logger.error("no constraints.txt or requirements.txt found in given paths")
        sys.exit(1)

    flag = True

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
            except InvalidRequirement as err:
                logger.error(f"{path}: {line}: {err}")
                flag = False

    if not flag:
        sys.exit(1)
