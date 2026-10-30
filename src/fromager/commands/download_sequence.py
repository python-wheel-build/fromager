import json
import logging
import typing
from concurrent import futures

import click
from packaging.requirements import Requirement
from packaging.version import Version

from .. import context, progress, read, sources, threading_utils, wheels
from ..log import req_ctxvar_context

logger = logging.getLogger(__name__)


def _skip_recorded_url(entry: dict[str, typing.Any], include_wheels: bool) -> bool:
    """Return whether a prebuilt path leaves the saved URL unused."""
    if entry["prebuilt"]:
        return not include_wheels
    source_url_type: str = entry["source_url_type"]
    return source_url_type == "prebuilt"


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
    default=threading_utils.get_cpu_count(),
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
    """Download sources and optional wheels from a build order.

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is a PyPI-compatible index used for optional wheel lookup

    Configured sources use their resolver's normal download operation. Entries
    that download a configured source or prebuilt wheel require the recorded
    provider to match current settings. Legacy entries retain the
    ``source_url_type`` selection behavior.

    """
    # The local wheel server is a trusted cache (wheels built in this or
    # prior runs).  An external sdist_server_url used as a wheel fallback
    # is an upstream index that needs cooldown and override hooks.
    use_cache_resolution = bool(wkctx.wheel_server_url)
    wheel_server_url = (
        wkctx.wheel_server_url if use_cache_resolution else sdist_server_url
    )

    logger.info("reading build order from %s", build_order_file)
    with read.open_file_or_url(build_order_file) as f:
        build_order = json.load(f)

    # Check recorded providers before workers can change the download cache
    # or a Git work directory. Skipped URLs do not use a source resolver.
    for entry in build_order:
        if _skip_recorded_url(entry, include_wheels):
            continue
        recorded_provider = entry.get("source_provider")
        req = Requirement(f"{entry['dist']}=={entry['version']}")
        source_resolver = wkctx.package_build_info(req).source_resolver
        current_provider = (
            source_resolver.provider if source_resolver is not None else None
        )
        if recorded_provider != current_provider:
            raise ValueError(
                f"{req}: build order records source provider {recorded_provider!r}, "
                f"current settings select {current_provider!r}; "
                "use matching settings or regenerate the build order"
            )

    def download_one(entry: dict[str, typing.Any]) -> None:
        req = Requirement(f"{entry['dist']}=={entry['version']}")
        with req_ctxvar_context(req):
            skip_recorded_url = _skip_recorded_url(entry, include_wheels)
            if entry["prebuilt"]:
                if not skip_recorded_url:
                    wheels.download_prebuilt_wheel(
                        ctx=wkctx,
                        req=req,
                        version=Version(entry["version"]),
                        download_url=entry["source_url"],
                        direct_download_directory=wkctx.wheels_prebuilt,
                    )
                else:
                    logger.info(f"{entry['dist']}: uses a pre-built wheel, skipping")
                return

            source_url_type = entry["source_url_type"]
            if skip_recorded_url:
                logger.info(
                    "%s: used a pre-built wheel, skipping source", entry["dist"]
                )
            else:
                source_resolver = wkctx.package_build_info(req).source_resolver
                try:
                    if source_resolver is not None or source_url_type == "sdist":
                        sources.download_source(
                            ctx=wkctx,
                            req=req,
                            version=Version(entry["version"]),
                            download_url=entry["source_url"],
                        )
                    else:
                        logger.info(
                            "%s: uses a %s downloader, skipping",
                            entry["dist"],
                            source_url_type,
                        )
                except Exception as err:
                    logger.error("failed to download source for %s: %s", req, err)
                    if not ignore_missing_sdists:
                        raise RuntimeError(
                            f"Failed to download source for {req}"
                        ) from err

            if include_wheels:
                try:
                    if use_cache_resolution:
                        resolved_url, _ = wheels.resolve_cached_wheel(
                            ctx=wkctx,
                            req=req,
                            cache_server_url=wheel_server_url,
                        )
                    else:
                        resolved_url, _ = wheels.resolve_prebuilt_wheel(
                            ctx=wkctx,
                            req=req,
                            wheel_server_urls=[wheel_server_url],
                        )
                    wheels.download_wheel(
                        req=req,
                        wheel_url=resolved_url,
                        output_directory=wkctx.wheels_downloads,
                    )
                except Exception as err:
                    logger.error(f"failed to download wheel for {req}: {err}")

    num_items = len(build_order)
    logger.debug(
        "starting up to %d concurrent downloads of %d items", num_threads, num_items
    )
    executor = futures.ThreadPoolExecutor(max_workers=num_threads)
    with progress.progress_context(num_items) as progress_bar:
        for _ in executor.map(download_one, build_order):
            progress_bar.update()
