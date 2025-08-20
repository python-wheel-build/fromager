import logging
from enum import Enum

import click
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, overrides, resolver

logger = logging.getLogger(__name__)


class DistributionType(Enum):
    """Distribution type for version lookup"""

    DEFAULT = "default"
    SDIST = "sdist"
    WHEEL = "wheel"
    BOTH = "both"


@click.command()
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
    "--ignore-no-versions/--no-ignore-no-versions",
    default=False,
    help="Do not treat missing versions as an error",
)
@click.option(
    "--format-as-requirements/--no-format-as-requirements",
    default=False,
    help="Format output as requirement specifiers (name==version) instead of just version numbers",
)
@click.argument("requirement_spec", required=True)
@click.pass_obj
def list_versions(
    wkctx: context.WorkContext,
    requirement_spec: str,
    distribution_type: str,
    sdist_server_url: str,
    ignore_no_versions: bool,
    format_as_requirements: bool,
) -> None:
    """List all available versions for a package requirement specifier.

    The REQUIREMENT_SPEC should be a package requirement specification like:
    - "package_name" (any version)
    - "package_name>=1.0" (versions >= 1.0)
    - "package_name==1.*" (versions matching 1.*)

    This command uses the get_resolver_provider hook to retrieve a resolver
    provider for the package in case there is a custom provider configured.

    Distribution types:
    - "default": Use package settings for include_sdists/include_wheels
    - "sdist": Only include source distributions
    - "wheel": Only include wheels
    - "both": Include both source distributions and wheels
    """
    try:
        req = Requirement(requirement_spec)
    except Exception as e:
        raise click.ClickException(
            f"Invalid requirement specification '{requirement_spec}': {e}"
        ) from e

    pbi = wkctx.package_build_info(req)
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
            package_settings = wkctx.settings.package_setting(req.name)
            include_sdists = package_settings.resolver_dist.include_sdists
            include_wheels = package_settings.resolver_dist.include_wheels

    logger.info(f"Looking up versions for {req.name}")
    if req.specifier:
        logger.info(f"Filtering versions with specifier: {req.specifier}")
    logger.info(
        f"Using distribution type: {dist_type.value} (sdists: {include_sdists}, wheels: {include_wheels})"
    )

    provider = overrides.find_and_invoke(
        req.name,
        "get_resolver_provider",
        resolver.default_resolver_provider,
        ctx=wkctx,
        req=req,
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=override_sdist_server_url,
    )

    # Get all available candidates from the provider
    candidates = list(
        provider.find_matches(
            identifier=req.name,
            requirements={req.name: [req]},
            incompatibilities={req.name: []},
        )
    )

    if not candidates:
        if ignore_no_versions:
            logger.warning(f"No versions found for {req.name}")
            return
        else:
            raise click.ClickException(f"No versions found for {req.name}")

    versions: list[Version] = sorted(set(candidate.version for candidate in candidates))
    logger.info(f"Found {len(versions)} version(s)")

    for version in versions:
        if format_as_requirements:
            print(f"{req.name}=={version}")
        else:
            print(version)
