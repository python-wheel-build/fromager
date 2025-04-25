import json
import os
import typing
from concurrent import futures

import click
from packaging.requirements import Requirement
from packaging.version import Version

from .. import context, progress, read, sources, wheels
from ..log import get_logger, requirement_ctxvar

logger = get_logger(__name__)


@click.command()
@click.argument("build_order_file")
@click.argument("sdist_server_url")
@click.option(
    "--include-wheels",
    "-w",
    default=False,
    is_flag=True,
)
@click.option(
    "--ignore-missing-sdists",
    default=False,
    is_flag=True,
)
@click.option(
    "--num-threads",
    default=os.cpu_count(),
    type=int,
)
@click.pass_obj
def download_sequence(
    wkctx: context.WorkContext,
    build_order_file: str,
    sdist_server_url: str,
    include_wheels: bool,
    ignore_missing_sdists: bool,
    num_threads: int,
) -> None:
    """Download a sequence of source distributions in order.

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'step download-source-archive' command only for items in
    the build order file that have source_url_type as sdist.

    """
    if wkctx.wheel_server_url:
        wheel_servers = [wkctx.wheel_server_url]
    else:
        wheel_servers = [sdist_server_url]

    logger.info("reading build order from %s", build_order_file)
    with read.open_file_or_url(build_order_file) as f:
        build_order = json.load(f)

    def download_one(entry: dict[str, typing.Any]):
        req = Requirement(f"{entry['dist']}=={entry['version']}")
        token = requirement_ctxvar.set(req)

        if entry["prebuilt"]:
            if include_wheels:
                wheels.download_wheel(req, entry["source_url"], wkctx.wheels_prebuilt)
            else:
                logger.info(f"{entry['dist']}: uses a pre-built wheel, skipping")
            return

        if entry["source_url_type"] == "sdist":
            try:
                sources.download_source(
                    ctx=wkctx,
                    req=req,
                    version=Version(entry["version"]),
                    download_url=entry["source_url"],
                )
            except Exception as err:
                logger.error(f"failed to download sdist for {req}: {err}")
                if not ignore_missing_sdists:
                    raise
        else:
            logger.info(
                f"{entry['dist']}: uses a {entry['source_url_type']} downloader, skipping"
            )

        if include_wheels:
            try:
                wheel_url, _ = wheels.resolve_prebuilt_wheel(
                    ctx=wkctx, req=req, wheel_server_urls=wheel_servers
                )
                wheels.download_wheel(
                    req=req,
                    wheel_url=wheel_url,
                    output_directory=wkctx.wheels_downloads,
                )
            except Exception as err:
                logger.error(f"failed to download wheel for {req}: {err}")
        requirement_ctxvar.reset(token)

    num_items = len(build_order)
    logger.debug(
        "starting up to %d concurrent downloads of %d items", num_threads, num_items
    )
    executor = futures.ThreadPoolExecutor(max_workers=num_threads)
    with progress.progress_context(num_items) as progress_bar:
        for _ in executor.map(download_one, build_order):
            progress_bar.update()
