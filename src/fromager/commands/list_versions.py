import click

from .. import resolver
from . import package


@click.command(deprecated=True)
@click.option(
    "--distribution-type",
    type=click.Choice(package.DistributionType, case_sensitive=False),
    default=package.DistributionType.DEFAULT.value,
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
@click.pass_context
def list_versions(
    ctx: click.Context,
    requirement_spec: str,
    distribution_type: str,
    sdist_server_url: str,
    ignore_no_versions: bool,
    format_as_requirements: bool,
) -> None:
    """List all available versions for a package requirement specifier."""
    click.secho("use 'fromager package list-versions'", bold=True)
    ctx.invoke(
        package.list_versions,
        requirement_spec=requirement_spec,
        distribution_type=distribution_type,
        sdist_server_url=sdist_server_url,
        ignore_no_versions=ignore_no_versions,
        format_as_requirements=format_as_requirements,
    )
