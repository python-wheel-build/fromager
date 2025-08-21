import csv
import json
import logging
import pathlib
import sys
from enum import Enum
from typing import TextIO

import click
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints, context, overrides, resolver
from fromager.commands.list_versions import DistributionType

logger = logging.getLogger(__name__)


class OutputFormat(Enum):
    """Output format for find-updates command"""

    REQUIREMENTS = "requirements"
    JSON = "json"
    CSV = "csv"


@click.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(OutputFormat, case_sensitive=False),
    default=OutputFormat.REQUIREMENTS.value,
    help="Output format (requirements: name==version, json: JSON array, csv: CSV with name,version columns)",
)
@click.option(
    "--distribution-type",
    type=click.Choice(DistributionType, case_sensitive=False),
    default=DistributionType.DEFAULT.value,
    help="Distribution type to include in version lookup (default: use package settings, sdist: source only, wheel: wheels only, both: include both sdists and wheels)",
)
@click.option(
    "--sdist-server-url",
    default=resolver.PYPI_SERVER_URL,
    help="URL to the Python package index to use for version lookup",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=pathlib.Path),
    help="Write output to file instead of stdout",
)
@click.argument(
    "constraints_file", type=click.Path(exists=True, path_type=pathlib.Path)
)
@click.pass_obj
def find_updates(
    wkctx: context.WorkContext,
    constraints_file: pathlib.Path,
    output_format: str,
    distribution_type: str,
    sdist_server_url: str,
    output: pathlib.Path | None,
) -> None:
    """Find available updates for packages with specific version constraints.

    This command reads a constraints file and for each package that has a
    supported constraint (==, <, <=, ~=, !=, ===), it lists newer versions available.
    Constraints with lower bounds (>=) are ignored as they don't pin to specific versions.

    The CONSTRAINTS_FILE should be a pip-style constraints file with entries like:
    - "package_name==1.0.0" (will look for versions > 1.0.0)
    - "package_name<2.0.0" (will look for versions >= 2.0.0)
    - "package_name<=1.5.0" (will look for versions > 1.5.0)
    - "package_name~=1.4.0" (will look for versions outside compatible range)
    - "package_name!=1.0.0" (will look for versions other than 1.0.0)
    - "package_name===1.0.0" (will look for versions other than exactly 1.0.0)
    - "package_name>=1.0.0" (ignored - not a specific constraint)

    Distribution types:
    - "default": Use package settings for include_sdists/include_wheels
    - "sdist": Only include source distributions
    - "wheel": Only include wheels
    - "both": Include both source distributions and wheels

    Output formats:
    - "requirements": List as requirement specifiers (package==version)
    - "json": JSON array of objects with "name" and "version" fields
    - "csv": CSV format with "name" and "version" columns

    Use --output to write results to a file instead of stdout.
    """
    # Load the constraints file
    constraint_loader = constraints.Constraints()
    constraint_loader.load_constraints_file(constraints_file)

    updates_found: list[dict[str, str]] = []

    # Process each constraint
    for package_name in constraint_loader:
        constraint = constraint_loader.get_constraint(package_name)
        if not constraint:
            continue

        # Check if this is a constraint we can check for updates (==, <, <=)
        constraint_version = _get_constraint_version(constraint)
        if not constraint_version:
            logger.debug(f"Skipping {package_name}: not a supported constraint type")
            continue

        logger.info(f"Looking for updates to {package_name} (constraint: {constraint})")

        # Find available versions for this package
        try:
            newer_versions = _find_newer_versions(
                wkctx,
                constraint,
                constraint_version,
                distribution_type,
                sdist_server_url,
            )

            if newer_versions:
                logger.info(
                    f"Found {len(newer_versions)} newer version(s) for {package_name}"
                )
                for version in newer_versions:
                    updates_found.append(
                        {"name": package_name, "version": str(version)}
                    )
            else:
                logger.debug(f"No newer versions found for {package_name}")

        except Exception as e:
            logger.warning(f"Could not check versions for {package_name}: {e}")

    # Output results in requested format
    if not updates_found:
        return

    # Determine output destination
    output_file: TextIO
    if output:
        output_file = output.open("w")
    else:
        output_file = sys.stdout

    try:
        output_fmt = OutputFormat(output_format)
        if output_fmt == OutputFormat.REQUIREMENTS:
            for update in updates_found:
                print(f"{update['name']}=={update['version']}", file=output_file)
        elif output_fmt == OutputFormat.JSON:
            json.dump(updates_found, output_file, indent=2)
            print(file=output_file)  # Add newline for better output
        elif output_fmt == OutputFormat.CSV:
            writer = csv.writer(output_file)
            writer.writerow(["name", "version"])
            for update in updates_found:
                writer.writerow([update["name"], update["version"]])
    finally:
        if output:
            output_file.close()


CONSTRAINT_OPERATORS = ("==", "<", "<=", "~=", "!=", "===")


def _get_constraint_version(constraint: Requirement) -> Version | None:
    """Extract version from supported constraint types (==, <, <=, ~=, !=, ===), return None if not supported."""
    if not constraint.specifier:
        return None

    # Look for supported constraint operators
    supported_specs = [
        spec for spec in constraint.specifier if spec.operator in CONSTRAINT_OPERATORS
    ]
    if len(supported_specs) != 1:
        return None

    # Parse the version from the constraint specifier
    try:
        return Version(supported_specs[0].version)
    except Exception:
        return None


def _find_newer_versions(
    wkctx: context.WorkContext,
    constraint: Requirement,
    constraint_version: Version,
    distribution_type: str,
    sdist_server_url: str,
) -> list[Version]:
    """Find versions that would be updates beyond the constraint for a package."""
    # Get package build info to determine distribution preferences
    pbi = wkctx.package_build_info(constraint)
    override_sdist_server_url = pbi.resolver_sdist_server_url(sdist_server_url)

    # Determine include flags based on distribution type
    dist_type = DistributionType(distribution_type)
    match dist_type:
        case DistributionType.SDIST:
            include_sdists = True
            include_wheels = False
        case DistributionType.WHEEL:
            include_sdists = False
            include_wheels = True
        case DistributionType.BOTH:
            include_sdists = True
            include_wheels = True
        case _:  # DEFAULT
            # Use package settings defaults
            package_settings = wkctx.settings.package_setting(constraint.name)
            include_sdists = package_settings.resolver_dist.include_sdists
            include_wheels = package_settings.resolver_dist.include_wheels

    # Get resolver provider
    provider = overrides.find_and_invoke(
        constraint.name,
        "get_resolver_provider",
        resolver.default_resolver_provider,
        ctx=wkctx,
        req=constraint,
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=override_sdist_server_url,
    )

    # Create a requirement without version constraints to get all available versions
    unconstrained_req = Requirement(constraint.name)

    # Get all available candidates
    candidates = list(
        provider.find_matches(
            identifier=constraint.name,
            requirements={constraint.name: [unconstrained_req]},
            incompatibilities={constraint.name: []},
        )
    )

    if not candidates:
        return []

    # Extract versions and filter based on constraint type
    all_versions = sorted(set(candidate.version for candidate in candidates))

    # Get the constraint operator to determine what "update" means
    constraint_spec = next(
        spec for spec in constraint.specifier if spec.operator in CONSTRAINT_OPERATORS
    )
    if constraint_spec.operator in ("==", "==="):
        # For equality constraints, find versions newer than the pinned version
        newer_versions = [v for v in all_versions if v > constraint_version]
    elif constraint_spec.operator in ("<", "<=", "~=", "!="):
        # For upper bound constraints, find versions that exceed the constraint
        # (these would be versions that violate the current constraint)
        newer_versions = [v for v in all_versions if v >= constraint_version]
    else:
        newer_versions = []

    return newer_versions
