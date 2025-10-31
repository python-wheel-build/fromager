import logging
from typing import Any

import click
from packaging.requirements import Requirement

from fromager import context
from fromager.request_session import session

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--pypi-base-url",
    default="https://pypi.org/pypi",
    help="Base URL for PyPI JSON API",
)
@click.argument("package_spec", required=True)
@click.pass_obj
def pypi_info(
    wkctx: context.WorkContext,
    package_spec: str,
    pypi_base_url: str,
) -> None:
    """Get information about a package from PyPI.

    The PACKAGE_SPEC should be a package name with optional version like:
    - "package_name" (latest version)
    - "package_name==1.0.0" (specific version)

    This command queries the PyPI JSON API to retrieve package information
    including license, URLs, and available distribution types.
    """
    try:
        req = Requirement(package_spec)
        package_name = req.name
        requested_version = None

        # Extract specific version if provided
        if req.specifier:
            specs = list(req.specifier)
            if len(specs) == 1 and specs[0].operator == "==":
                requested_version = specs[0].version
            else:
                raise click.ClickException(
                    f"Only exact version specifications (==) are supported, got: {req.specifier}"
                )
    except Exception as e:
        raise click.ClickException(
            f"Invalid package specification '{package_spec}': {e}"
        ) from e

    logger.info(f"Fetching information for {package_name}")
    if requested_version:
        logger.info(f"Requesting specific version: {requested_version}")

    try:
        package_info = _get_package_info(pypi_base_url, package_name, requested_version)
        _display_package_info(package_info, package_name, requested_version)
    except PackageNotFoundError as e:
        logger.error(str(e))
        raise click.ClickException(str(e)) from e
    except Exception as e:
        logger.error(f"Failed to retrieve package information: {e}")
        raise click.ClickException(
            f"Failed to retrieve package information: {e}"
        ) from e


class PackageNotFoundError(Exception):
    """Raised when a package or version is not found on PyPI."""

    pass


def _get_package_info(
    pypi_base_url: str, package_name: str, version: str | None = None
) -> dict[str, Any]:
    """Fetch package information from PyPI JSON API."""
    if version:
        url = f"{pypi_base_url}/{package_name}/{version}/json"
    else:
        url = f"{pypi_base_url}/{package_name}/json"

    logger.debug(f"Requesting PyPI data from: {url}")

    response = session.get(url)
    if response.status_code == 404:
        if version:
            raise PackageNotFoundError(
                f"Package '{package_name}' version '{version}' not found on PyPI"
            )
        else:
            raise PackageNotFoundError(f"Package '{package_name}' not found on PyPI")

    response.raise_for_status()
    return response.json()


def _display_package_info(
    package_data: dict[str, Any], package_name: str, requested_version: str | None
) -> None:
    """Display package information in a structured format."""
    info = package_data.get("info", {})
    urls = package_data.get("urls", [])

    # Package name and version
    name = info.get("name", package_name)
    version = info.get("version", "unknown")

    print(f"Package: {name}")
    print(f"Version: {version}")

    # Package found status
    print("Found on PyPI: Yes")

    # License information
    license_info = info.get("license") or "Not specified"
    # Handle cases where license is empty string or None
    if not license_info or license_info.strip() == "":
        license_info = "Not specified"
    print(f"License: {license_info}")

    # URLs
    home_page = info.get("home_page") or info.get("project_url")
    if home_page:
        print(f"Homepage: {home_page}")
    else:
        print("Homepage: Not specified")

    # Check for other relevant URLs
    project_urls = info.get("project_urls") or {}
    if isinstance(project_urls, dict):
        for url_type, url in project_urls.items():
            if url_type.lower() in ("repository", "source", "github", "gitlab"):
                print(f"Repository: {url}")
                break

    # Distribution types analysis
    has_sdist = False
    has_wheel = False

    for url_info in urls:
        package_type = url_info.get("packagetype", "")
        if package_type == "sdist":
            has_sdist = True
        elif package_type == "bdist_wheel":
            has_wheel = True

    print(f"Has source distribution (sdist): {'Yes' if has_sdist else 'No'}")
    print(f"Has wheel: {'Yes' if has_wheel else 'No'}")

    # Summary
    logger.info(f"Package information retrieved successfully for {name} {version}")
