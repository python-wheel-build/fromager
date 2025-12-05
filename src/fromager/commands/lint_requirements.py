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
@click.option(
    "--resolve-requirements/--no-resolve-requirements",
    default=False,
    help="Resolve requirement and fail if a package or version cannot be resolved",
    show_default=True,
)
@click.pass_obj
def lint_requirements(
    wkctx: context.WorkContext,
    resolve_requirements: bool,
    input_files_path: list[pathlib.Path],
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

    failures: list[str] = []

    # Create bootstrapper for requirement resolution
    bt = bootstrapper.Bootstrapper(
        ctx=wkctx,
        progressbar=progress.Progressbar(None),
        prev_graph=None,
        cache_wheel_server_url=None,
        sdist_only=True,
    )

    for path in input_files_path:
        is_constraints: bool = path.name.endswith("constraints.txt")
        parsed_lines = requirements_file.parse_requirements_file(path)
        unique_entries: dict[tuple[str, str], Requirement] = {}
        for line in parsed_lines:
            try:
                requirement = Requirement(line)
                marker_key = str(requirement.marker) if requirement.marker else ""
                unique_key = (requirement.name, marker_key)

                if is_constraints:
                    if unique_key in unique_entries:
                        raise InvalidRequirement(
                            f"Duplicate entry, first found: {unique_entries[unique_key]}"
                        )
                    unique_entries[unique_key] = requirement
                    if requirement.extras:
                        raise InvalidRequirement(
                            f"{requirement.name}: Constraints files cannot contain extra dependencies"
                        )
                    if not requirement.specifier:
                        raise InvalidRequirement(
                            f"{requirement.name}: Constraints must have a version specifier"
                        )
            except InvalidRequirement as err:
                msg = f"{path}: {line}: {err}"
                logger.error(msg)
                failures.append(msg)

            # Resolve the requirement to ensure it can be found
            # Skip resolution for constraints files as they should only specify versions
            if resolve_requirements and not is_constraints:
                token = requirement_ctxvar.set(requirement)
                try:
                    _, version = bt.resolve_version(
                        req=requirement,
                        req_type=RequirementType.TOP_LEVEL,
                    )
                    logger.info(f"{requirement} resolves to {version}")
                except Exception as err:
                    logger.error(
                        f"{path}: {line}: Failed to resolve requirement: {err}"
                    )
                    failures.append(f"{path}: {line}: {err}")
                finally:
                    requirement_ctxvar.reset(token)

    if failures:
        click.echo("Validation error:", err=True)
        for failure in failures:
            click.echo(f" - {failure}", err=True)
        click.echo(
            f"ERROR: {len(failures)} failure(s) while validating {len(input_files_path)} file(s).",
            err=True,
        )
        sys.exit(1)
    else:
        click.echo(f"Resolve requirements: {resolve_requirements}")
        click.echo(f"Successfully validated {len(input_files_path)} file(s).")
