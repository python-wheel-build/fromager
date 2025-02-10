import logging
import sys

import click
from packaging.requirements import InvalidRequirement, Requirement

from fromager import requirements_file

logger = logging.getLogger(__name__)


@click.command()
@click.argument(
    "input_files_path", nargs=-1, required=True, type=click.Path(exists=False)
)
def lint_requirements(input_files_path: list[click.Path]) -> None:
    """
    Command to lint the constraints.txt and requirements.txt files
    This command takes a single wildcard path string for constraints.txt and requirements.txt.
    It checks the formatting of these files and reports issues if found.
    """

    if len(input_files_path) == 0:
        logger.error("no constraints.txt or requirements.txt found in given paths")
        sys.exit(1)

    flag = True

    for path in input_files_path:
        parsed_lines = requirements_file.parse_requirements_file(str(path))
        for line in parsed_lines:
            try:
                Requirement(line)
            except InvalidRequirement as err:
                logger.error(f"{path}: {line}: {err}")
                flag = False

    if not flag:
        sys.exit(1)
