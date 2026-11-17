"""Download setuptools wheels for the hook-prebuilt end-to-end test."""

import logging
import pathlib

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, downloads, packagesettings

logger = logging.getLogger(__name__)


def download_source(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    download_url: str,
    sdists_downloads_dir: pathlib.Path,
) -> packagesettings.DownloadedSource:
    """Download a prebuilt wheel and return its path and artifact kind."""
    logger.info("download_source hook downloading %s==%s", req.name, version)
    path = downloads.download_wheel(
        destination_dir=ctx.wheels_prebuilt,
        url=download_url,
    )
    return packagesettings.DownloadedSource(
        path=path, kind=packagesettings.DownloadKind.prebuilt_wheel
    )
