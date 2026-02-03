import datetime
import enum
import logging
import sys
import typing

import click
import pypi_simple
from packaging.requirements import Requirement
from packaging.version import Version
from resolvelib.resolvers import ResolverException

from .. import context, log, overrides, packagesettings, request_session, resolver
from ..candidate import Candidate

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)


def sdist_server_url_option(func: typing.Callable) -> typing.Callable:
    """Add --sdist-server-url Click option"""
    return click.option(
        "--sdist-server-url",
        default=resolver.PYPI_SERVER_URL,
        help="URL to the Python package index to use for version lookup",
    )(func)


class DistributionType(enum.Enum):
    """Distribution type for version lookup"""

    DEFAULT = "default"
    SDIST = "sdist"
    WHEEL = "wheel"
    BOTH = "both"


def distribution_type_option(func: typing.Callable) -> typing.Callable:
    """Add --distribution-type Click option"""
    return click.option(
        "--distribution-type",
        type=click.Choice(DistributionType, case_sensitive=False),
        default=DistributionType.DEFAULT.value,
        help=(
            "Distribution type to include in version lookup "
            "(default: use package settings, sdist: source only, "
            "wheel: wheels only, both: include both sdists and wheels)"
        ),
    )(func)


def parse_distribution_option(
    distribution_type: str, pbi: packagesettings.PackageBuildInfo
) -> tuple[bool, bool]:
    """Parse distribution_type option

    return include_sdists, include_wheels
    """
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
            include_sdists = pbi.resolver_include_sdists
            include_wheels = pbi.resolver_include_wheels
    click.secho(
        f"Using distribution type: {dist_type.value} (sdists: {include_sdists}, wheels: {include_wheels})"
    )
    return include_sdists, include_wheels


@click.group()
def package() -> None:
    "Commands for resolving package versions"
    pass


@package.command()
@distribution_type_option
@sdist_server_url_option
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

    logger.info(f"Looking up versions for {req.name}")
    if req.specifier:
        logger.info(f"Filtering versions with specifier: {req.specifier}")

    pbi = wkctx.package_build_info(req)
    override_sdist_server_url = pbi.resolver_sdist_server_url(sdist_server_url)

    include_sdists, include_wheels = parse_distribution_option(
        distribution_type,
        pbi,
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


def _versions_string(versions: typing.Iterable[Version]) -> str:
    """Convert iterable of versions to sorted string"""
    return ", ".join(str(version) for version in sorted(versions))


def _get_latest_package(
    upload_times: typing.Iterable[datetime.datetime | None],
) -> datetime.datetime | None:
    """Get latest release, convert to local TZ"""
    latest = max((dt for dt in upload_times if dt is not None), default=None)
    if latest is not None:
        return latest.astimezone().replace(microsecond=0)
    else:
        return None


def _resolve_fromager(
    ctx: context.WorkContext,
    req: Requirement,
    global_constraint: Requirement | None,
    distribution_type: str,
    sdist_server_url: str,
) -> set[Version] | None:
    # print package build info settings (overrides)
    pbi = ctx.package_build_info(req)
    override_sdist_server_url = pbi.resolver_sdist_server_url(sdist_server_url)

    if pbi.has_customizations:
        click.secho(
            "NOTE: Package has customizations (config override, plugin, patches).",
            bold=True,
        )
    else:
        click.secho("Package uses standard settings.")
    click.secho(f"- sdist server url: {override_sdist_server_url}")
    click.secho(f"- resolver includes sdists: {pbi.resolver_include_sdists}")
    click.secho(f"- resolver includes wheels: {pbi.resolver_include_wheels}")
    click.secho(f"- wheel server url: {pbi.wheel_server_url}")
    click.secho(f"- download url: {pbi.download_source_url(resolve_template=False)}")
    click.secho(f"- prebuilt wheel: {pbi.pre_built}")

    # resolve package with Fromager's resolver and settings.
    include_sdists, include_wheels = parse_distribution_option(distribution_type, pbi)
    provider = overrides.find_and_invoke(
        req.name,
        "get_resolver_provider",
        resolver.default_resolver_provider,
        ctx=ctx,
        req=req,
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=override_sdist_server_url,
        ignore_platform=pbi.resolver_ignore_platform,
    )

    click.echo()
    click.secho(f"get_resolver_provider returns provider '{type(provider).__name__}'")

    try:
        candidates: list[Candidate] = list(
            provider.find_matches(
                identifier=req.name,
                requirements={req.name: [req]},
                incompatibilities={req.name: []},
            )
        )
    except ResolverException as e:
        click.secho(
            f"failed to resolve package with Fromager: {e}", err=True, bold=True
        )
        return None

    fromager_versions: set[Version] = set(candidate.version for candidate in candidates)
    click.secho(
        f"found {len(candidates)} Fromager candidates with "
        f"{len(fromager_versions)} unique versions for "
        f"req: '{req}', global constraint: '{global_constraint}'",
    )

    latest = _get_latest_package(candidate.upload_time for candidate in candidates)
    click.secho(
        f"- latest Fromager candidate for '{req}': {latest if latest else 'unknown'}",
    )
    click.secho(
        f"- Fromager versions: {_versions_string(fromager_versions)}", bold=True
    )

    return fromager_versions


def _resolve_pypi(
    ctx: context.WorkContext, req: Requirement, global_constraint: Requirement | None
) -> set[Version] | None:
    # resolve package from PyPI
    pypi_client = pypi_simple.PyPISimple(
        accept=pypi_simple.ACCEPT_JSON_ONLY,
        session=request_session.session,
    )
    try:
        pypi_package = pypi_client.get_project_page(req.name)
    except Exception as e:
        click.secho(
            f"failed to fetch package index from pypi.org: {e}", err=True, bold=True
        )
        return None

    pypi_versions_wheels: set[Version] = set()
    pypi_versions_sdists: set[Version] = set()
    pypi_upload_times: list[datetime.datetime | None] = []
    has_purelib: bool = False
    has_platlib: bool = False
    for pkg in pypi_package.packages:
        if pkg.package_type not in {"sdist", "wheel"} or not pkg.version:
            continue
        version = Version(pkg.version)
        if pkg.is_yanked:
            logger.debug("%s is yanked")
            continue
        if req.specifier and version not in req.specifier:
            logger.debug("%s is not in requirment specifier %s", version, req.specifier)
            continue
        if global_constraint is not None and version not in global_constraint.specifier:
            logger.debug(
                "%s is excluded by global constraint %s",
                version,
                global_constraint,
            )
            continue
        pypi_upload_times.append(pkg.upload_time)
        if pkg.package_type == "wheel":
            pypi_versions_wheels.add(version)
            if pkg.filename.endswith("-none-any.whl"):
                has_purelib = True
            else:
                has_platlib = True
        else:
            pypi_versions_sdists.add(version)

    pypi_versions: set[Version] = pypi_versions_sdists | pypi_versions_wheels
    click.secho(
        f"found {len(pypi_versions)} versions on PyPI for "
        f"req: '{req}', global constraint: '{global_constraint}'",
    )

    latest = _get_latest_package(pypi_upload_times)
    click.secho(
        f"- latest PyPI release for '{req}': {latest if latest else 'unknown'}",
    )

    # platlib or purelib? A package can have purelib and platlib wheels
    if has_platlib:
        click.secho(
            "- package has platlib wheels (compiled C/C++/Go/Rust extension)", bold=True
        )
    if has_purelib:
        click.secho("- package has purelib wheels (pure Python code)")

    click.secho(f"- PyPI versions: {_versions_string(pypi_versions)}", bold=True)
    # print missing sdists or missing wheels
    diff = pypi_versions_sdists.difference(pypi_versions_wheels)
    if diff:
        click.secho(f"- only sdists on PyPI: {_versions_string(diff)}")
    diff = pypi_versions_wheels.difference(pypi_versions_sdists)
    if diff:
        click.secho(f"- only wheels on PyPI: {_versions_string(diff)}")
    return pypi_versions


@package.command()
@distribution_type_option
@sdist_server_url_option
@click.argument("requirement_spec", required=True)
@click.pass_obj
def resolve(
    wkctx: context.WorkContext,
    requirement_spec: str,
    distribution_type: str,
    sdist_server_url: str,
) -> None:
    """Resolve a package with Fromager's resolver and PyPI

    The package resolver subcommand is a debug tool. It shows information
    about the package's resolver configuration and resolves a package in two
    way. First, it resolves with Fromager's resolver. Second, it performs a
    simple query against PyPI and compares the results.

    Usage::

       $ fromager --variant cpu package resolve 'fromager>=0.70'
    """

    try:
        req = Requirement(requirement_spec)
    except Exception as e:
        raise click.ClickException(
            f"Invalid requirement specification '{requirement_spec}': {e}"
        ) from e

    with log.req_ctxvar_context(req):
        click.secho(
            f"resolving requirement for '{req}' (variant: {wkctx.variant})", bold=True
        )

        global_constraint = wkctx.constraints.get_constraint(req.name)
        if global_constraint is not None:
            click.secho(
                f"Package has a global constraint {global_constraint}.", bold=True
            )
        else:
            click.secho("Package has not global constraint.")

        # resolve package with Fromager's resolver
        click.echo()
        fromager_versions = _resolve_fromager(
            wkctx, req, global_constraint, distribution_type, sdist_server_url
        )

        # resolve package on PyPI
        click.echo()
        pypi_versions = _resolve_pypi(wkctx, req, global_constraint)

        # print differences between Fromager and PyPI
        if fromager_versions is not None and pypi_versions is not None:
            diff = fromager_versions.difference(pypi_versions)
            if diff:
                click.secho(f"- missing from PyPI: {_versions_string(diff)}", bold=True)
            diff = pypi_versions.difference(fromager_versions)
            if diff:
                click.secho(
                    f"- missing from Fromager: {_versions_string(diff)}", bold=True
                )

        if not fromager_versions:
            click.secho("Fromager lookup failed", err=True)
            sys.exit(2)
