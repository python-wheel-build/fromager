import json
import logging

import click
from packaging.requirements import Requirement

from .. import context, sdist, sources

logger = logging.getLogger(__name__)


@click.command()
@click.argument("build_order_file")
@click.argument("sdist_server_url")
@click.option(
    "--include-wheels",
    "-w",
    default=False,
    is_flag=True,
)
@click.pass_obj
def download_sequence(
    wkctx: context.WorkContext,
    build_order_file: str,
    sdist_server_url: str,
    include_wheels: str,
):
    """Download a sequence of source distributions in order.

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'step download-source-archive' command for each item in
    the build order file.

    """
    if wkctx.wheel_server_url:
        wheel_servers = [wkctx.wheel_server_url]
    else:
        wheel_servers = [sdist_server_url]

    with open(build_order_file, "r") as f:
        for entry in json.load(f):
            if entry["prebuilt"]:
                logger.info(f"{entry['dist']} uses a pre-built wheel, skipping")
                continue

            req = Requirement(f"{entry['dist']}=={entry['version']}")

            if entry["source_url_type"] == "sdist":
                sources.download_source(wkctx, req, [sdist_server_url])
            else:
                logger.info(
                    f"{entry['dist']} uses a {entry['source_url_type']} downloader, skipping"
                )

            if include_wheels:
                try:
                    sdist.download_wheel(
                        wkctx,
                        req,
                        wkctx.wheels_downloads,
                        wheel_servers,
                    )
                except Exception as err:
                    logger.error(f"Failed to download wheel for {req}: {err}")
