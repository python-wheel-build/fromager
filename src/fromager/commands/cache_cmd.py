"""CLI commands for cache management and observability."""

import json
import logging
import pathlib

import click
import rich
import rich.box
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from rich.table import Table

from fromager import context
from fromager.cache import (
    CacheBackend,
    CacheCollection,
    CacheManager,
    LocalDirectoryBackend,
    RemotePEP503Backend,
    StoreRouter,
)

logger = logging.getLogger(__name__)


def _build_cache_manager(
    wkctx: context.WorkContext,
    cache_url: str | None = None,
    toplevel_reqs: list[Requirement] | None = None,
) -> CacheManager:
    """Construct a CacheManager from the WorkContext configuration.

    If the context already has a cache configured, return it.
    Otherwise, build one from the standard filesystem layout.

    When a non-default variant is active and top-level requirements are provided,
    two collections are created:
    - A variant-specific collection for packages listed in the variant's
      requirements file (the "main" packages for this build)
    - A shared "default" collection for unlisted transitive dependencies

    Newly built wheels are routed by the StoreRouter: packages listed in the
    variant requirements go to the variant collection, unlisted deps to default.

    Args:
        wkctx: The work context providing local paths and variant info.
        cache_url: Optional URL to a remote PEP 503 cache server.
        toplevel_reqs: Top-level requirements from the variant's requirements
            file. These define which packages belong to the variant collection.
    """
    if wkctx.cache is not None:
        return wkctx.cache

    # Shared (default) collection: downloads + prebuilt + optional remote
    shared_backend = LocalDirectoryBackend(
        wkctx.wheels_downloads, backend_name="local:downloads"
    )
    prebuilt_backend = LocalDirectoryBackend(
        wkctx.wheels_prebuilt, backend_name="local:prebuilt"
    )

    shared_backends: list[CacheBackend] = [shared_backend, prebuilt_backend]

    if cache_url:
        remote_backend = RemotePEP503Backend(
            server_url=cache_url,
            download_dir=wkctx.wheels_downloads,
            backend_name=f"remote:{cache_url}",
        )
        shared_backends.append(remote_backend)

    default_collection = CacheCollection(
        name="default",
        backends=shared_backends,
        store_backend=shared_backend,
    )

    collections: dict[str, CacheCollection] = {"default": default_collection}
    search_order: list[str] = ["default"]

    # Variant-specific collection for packages listed in the requirements file
    variant_packages = {canonicalize_name(r.name) for r in (toplevel_reqs or [])}

    if variant_packages and wkctx.variant != "cpu":
        variant_dir = wkctx.wheels_repo / "variants" / wkctx.variant
        variant_dir.mkdir(parents=True, exist_ok=True)
        variant_backend = LocalDirectoryBackend(
            variant_dir, backend_name=f"local:{wkctx.variant}"
        )

        variant_backends: list[CacheBackend] = [variant_backend, prebuilt_backend]
        variant_collection = CacheCollection(
            name=wkctx.variant,
            backends=variant_backends,
            store_backend=variant_backend,
        )
        collections[wkctx.variant] = variant_collection
        search_order = [wkctx.variant, "default"]

    router = StoreRouter(
        overrides={},
        variant_packages=variant_packages,
        active_variant=wkctx.variant,
    )

    manager = CacheManager(
        collections=collections,
        search_order=search_order,
        store_routing=router,
    )
    manager.initialize()
    return manager


@click.group()
def cache() -> None:
    """Manage the fromager wheel cache."""
    pass


@cache.command(name="list")
@click.option(
    "--collection",
    default=None,
    help="Only list artifacts from this collection.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    help="Output format (default: table).",
)
@click.pass_obj
def cache_list(
    wkctx: context.WorkContext,
    collection: str | None,
    output_format: str,
) -> None:
    """List all cached wheel artifacts."""
    manager = _build_cache_manager(wkctx)

    entries = []
    for coll_name, coll in manager.collections.items():
        if collection and coll_name != collection:
            continue
        for backend in coll.backends:
            if not hasattr(backend, "_index"):
                continue
            for key, info in backend._index.items():
                entries.append(
                    {
                        "collection": coll_name,
                        "backend": backend.name,
                        "package": str(key.package),
                        "version": str(key.version),
                        "build_tag": (
                            f"{key.build_tag[0]}{key.build_tag[1]}"
                            if key.build_tag
                            else ""
                        ),
                        "filename": info.filename,
                        "size_bytes": info.size_bytes or 0,
                    }
                )

    entries.sort(key=lambda e: (e["collection"], e["package"], e["version"]))

    if output_format == "json":
        click.echo(json.dumps(entries, indent=2))
        return

    if not entries:
        click.echo("No cached wheels found.")
        return

    table = Table(title="Cached Wheels", box=rich.box.SIMPLE)
    table.add_column("Collection", no_wrap=True)
    table.add_column("Package", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Build Tag", no_wrap=True)
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("Backend", no_wrap=True)

    for entry in entries:
        size = _format_size(entry["size_bytes"])
        table.add_row(
            entry["collection"],
            entry["package"],
            entry["version"],
            entry["build_tag"],
            size,
            entry["backend"],
        )

    console = rich.get_console()
    console.print(table)
    console.print(f"\nTotal: {len(entries)} wheel(s)")


@cache.command(name="stats")
@click.pass_obj
def cache_stats(wkctx: context.WorkContext) -> None:
    """Show cache statistics (hit/miss rates from last run)."""
    manager = _build_cache_manager(wkctx)

    table = Table(title="Cache Statistics", box=rich.box.SIMPLE)
    table.add_column("Metric", no_wrap=True)
    table.add_column("Value", justify="right", no_wrap=True)

    summary = manager.stats.summary()

    table.add_row("Total lookups", str(summary["hits"]["total"] + summary["misses"]))
    table.add_row("Hits", str(summary["hits"]["total"]))
    table.add_row("Misses", str(summary["misses"]))
    table.add_row("Hit rate", f"{summary['hit_rate']:.1%}")
    table.add_row("Stores", str(summary["stores"]))

    if summary["hits"]["by_collection"]:
        table.add_section()
        for coll, count in summary["hits"]["by_collection"].items():
            table.add_row(f"  Hits from {coll}", str(count))

    # Show per-collection inventory counts
    table.add_section()
    total_wheels = 0
    total_size = 0
    for coll_name, coll in manager.collections.items():
        coll_count = 0
        coll_size = 0
        for backend in coll.backends:
            if hasattr(backend, "_index"):
                coll_count += len(backend._index)
                coll_size += sum(
                    (info.size_bytes or 0) for info in backend._index.values()
                )
        table.add_row(f"  {coll_name} wheels", str(coll_count))
        table.add_row(f"  {coll_name} size", _format_size(coll_size))
        total_wheels += coll_count
        total_size += coll_size

    table.add_section()
    table.add_row("Total wheels on disk", str(total_wheels))
    table.add_row("Total size on disk", _format_size(total_size))

    console = rich.get_console()
    console.print(table)


@cache.command()
@click.option(
    "--remove-missing",
    is_flag=True,
    default=False,
    help="Remove index entries for files that no longer exist on disk.",
)
@click.pass_obj
def verify(wkctx: context.WorkContext, remove_missing: bool) -> None:
    """Verify cache integrity: check that indexed files exist on disk."""
    manager = _build_cache_manager(wkctx)

    missing = []
    checked = 0

    for coll_name, coll in manager.collections.items():
        for backend in coll.backends:
            if not isinstance(backend, LocalDirectoryBackend):
                continue
            for key, info in list(backend._index.items()):
                checked += 1
                file_path = pathlib.Path(info.url_or_path)
                if not file_path.exists():
                    missing.append(
                        {
                            "collection": coll_name,
                            "backend": backend.name,
                            "key": str(key),
                            "path": str(file_path),
                        }
                    )
                    if remove_missing:
                        del backend._index[key]

    if not missing:
        click.echo(f"All {checked} cached artifacts verified OK.")
        return

    click.echo(f"Found {len(missing)} missing artifact(s) out of {checked} checked:")
    for m in missing:
        action = " [removed from index]" if remove_missing else ""
        click.echo(f"  {m['collection']}/{m['key']}: {m['path']}{action}")


@cache.command()
@click.argument("packages", nargs=-1)
@click.option(
    "--all",
    "invalidate_all",
    is_flag=True,
    default=False,
    help="Invalidate the entire cache.",
)
@click.option(
    "--collection",
    default=None,
    help="Only invalidate within this collection.",
)
@click.pass_obj
def invalidate(
    wkctx: context.WorkContext,
    packages: tuple[str, ...],
    invalidate_all: bool,
    collection: str | None,
) -> None:
    """Invalidate (remove) cached wheels for specific packages.

    Pass package names as arguments, or use --all to clear everything.
    """
    if not packages and not invalidate_all:
        raise click.UsageError("Specify package names or use --all.")

    manager = _build_cache_manager(wkctx)
    removed = 0

    target_packages = {canonicalize_name(p) for p in packages} if packages else None

    for coll_name, coll in manager.collections.items():
        if collection and coll_name != collection:
            continue
        for backend in coll.backends:
            if not isinstance(backend, LocalDirectoryBackend):
                continue
            keys_to_remove = []
            for key, info in backend._index.items():
                if target_packages and key.package not in target_packages:
                    continue
                keys_to_remove.append((key, info))

            for key, info in keys_to_remove:
                file_path = pathlib.Path(info.url_or_path)
                if file_path.exists():
                    file_path.unlink()
                    logger.info("removed %s", file_path)
                del backend._index[key]
                removed += 1

    click.echo(f"Invalidated {removed} cached artifact(s).")


@cache.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be removed without actually deleting.",
)
@click.option(
    "--keep-latest",
    type=int,
    default=1,
    help="Keep this many build tags per package+version (default: 1).",
)
@click.pass_obj
def gc(
    wkctx: context.WorkContext,
    dry_run: bool,
    keep_latest: int,
) -> None:
    """Garbage-collect old builds, keeping only the latest build tags.

    For each package+version, removes all but the --keep-latest most
    recent builds (highest build tag number).
    """
    manager = _build_cache_manager(wkctx)
    removed = 0
    freed_bytes = 0

    for _coll_name, coll in manager.collections.items():
        for backend in coll.backends:
            if not isinstance(backend, LocalDirectoryBackend):
                continue

            # Group by (package, version)
            groups: dict[tuple, list] = {}
            for key, info in backend._index.items():
                group_key = (key.package, key.version)
                groups.setdefault(group_key, []).append((key, info))

            for _group_key, entries in groups.items():
                if len(entries) <= keep_latest:
                    continue

                # Sort by build tag number descending
                entries.sort(
                    key=lambda e: e[0].build_tag[0] if e[0].build_tag else 0,
                    reverse=True,
                )
                to_remove = entries[keep_latest:]

                for key, info in to_remove:
                    file_path = pathlib.Path(info.url_or_path)
                    size = info.size_bytes or 0
                    if dry_run:
                        click.echo(
                            f"  would remove: {info.filename} ({_format_size(size)})"
                        )
                    else:
                        if file_path.exists():
                            file_path.unlink()
                        del backend._index[key]
                        logger.info("gc removed %s", file_path)
                    removed += 1
                    freed_bytes += size

    verb = "Would remove" if dry_run else "Removed"
    click.echo(f"{verb} {removed} old build(s), freeing {_format_size(freed_bytes)}.")


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"
