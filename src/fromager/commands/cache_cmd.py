"""CLI commands for cache management and observability."""

import json
import logging
import pathlib

import click
import rich
import rich.box
from packaging.utils import canonicalize_name
from rich.table import Table

from fromager import cache, context

logger = logging.getLogger(__name__)


@click.group(name="cache")
def cache_cli() -> None:
    """Manage the fromager wheel cache."""
    pass


@cache_cli.command(name="list")
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
    output_format: str,
) -> None:
    """List all cached wheel artifacts."""
    manager = cache.build_cache_manager(wkctx)

    entries: list[dict[str, str | int]] = []
    for backend in manager.lookup_backends:
        for key, info in backend.items():
            entries.append(
                {
                    "backend": backend.name,
                    "package": str(key.package),
                    "version": str(key.version),
                    "build_tag": (
                        f"{key.build_tag[0]}{key.build_tag[1]}" if key.build_tag else ""
                    ),
                    "filename": info.filename,
                    "size_bytes": info.size_bytes or 0,
                }
            )

    entries.sort(
        key=lambda e: (str(e["backend"]), str(e["package"]), str(e["version"]))
    )

    if output_format == "json":
        click.echo(json.dumps(entries, indent=2))
        return

    if not entries:
        click.echo("No cached wheels found.")
        return

    table = Table(title="Cached Wheels", box=rich.box.SIMPLE)
    table.add_column("Package", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Build Tag", no_wrap=True)
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("Backend", no_wrap=True)

    for entry in entries:
        size = _format_size(int(entry["size_bytes"]))
        table.add_row(
            str(entry["package"]),
            str(entry["version"]),
            str(entry["build_tag"]),
            size,
            str(entry["backend"]),
        )

    console = rich.get_console()
    console.print(table)
    console.print(f"\nTotal: {len(entries)} wheel(s)")


@cache_cli.command(name="stats")
@click.pass_obj
def cache_stats(wkctx: context.WorkContext) -> None:
    """Show on-disk cache inventory by backend.

    Hit/miss rates are recorded in-memory during a bootstrap run and are not
    persisted, so this command reports backend inventory only.
    """
    manager = cache.build_cache_manager(wkctx)

    table = Table(title="Cache Inventory", box=rich.box.SIMPLE)
    table.add_column("Metric", no_wrap=True)
    table.add_column("Value", justify="right", no_wrap=True)

    total_wheels = 0
    total_size = 0
    for backend in manager.lookup_backends:
        backend_count = 0
        backend_size = 0
        for _key, info in backend.items():
            backend_count += 1
            backend_size += info.size_bytes or 0
        table.add_row(f"{backend.name} wheels", str(backend_count))
        table.add_row(f"{backend.name} size", _format_size(backend_size))
        total_wheels += backend_count
        total_size += backend_size

    table.add_section()
    table.add_row("Total wheels on disk", str(total_wheels))
    table.add_row("Total size on disk", _format_size(total_size))

    console = rich.get_console()
    console.print(table)


@cache_cli.command()
@click.option(
    "--remove-missing",
    is_flag=True,
    default=False,
    help="Remove index entries for files that no longer exist on disk.",
)
@click.pass_obj
def verify(wkctx: context.WorkContext, remove_missing: bool) -> None:
    """Verify cache integrity: check that indexed files exist on disk."""
    manager = cache.build_cache_manager(wkctx)

    missing: list[dict[str, str]] = []
    checked = 0
    backends_to_rescan: list[cache.LocalDirectoryBackend] = []

    for backend in manager.lookup_backends:
        if not isinstance(backend, cache.LocalDirectoryBackend):
            continue
        backend_had_missing = False
        for key, info in backend.items():
            checked += 1
            file_path = pathlib.Path(info.url_or_path)
            if not file_path.exists():
                missing.append(
                    {
                        "backend": backend.name,
                        "key": str(key),
                        "path": str(file_path),
                    }
                )
                backend_had_missing = True
        if remove_missing and backend_had_missing:
            backends_to_rescan.append(backend)

    for backend in backends_to_rescan:
        backend.scan()

    if not missing:
        click.echo(f"All {checked} cached artifacts verified OK.")
        return

    click.echo(f"Found {len(missing)} missing artifact(s) out of {checked} checked:")
    for m in missing:
        action = " [removed from index]" if remove_missing else ""
        click.echo(f"  {m['backend']}/{m['key']}: {m['path']}{action}")


@cache_cli.command()
@click.argument("packages", nargs=-1)
@click.option(
    "--all",
    "invalidate_all",
    is_flag=True,
    default=False,
    help="Invalidate the entire cache.",
)
@click.pass_obj
def invalidate(
    wkctx: context.WorkContext,
    packages: tuple[str, ...],
    invalidate_all: bool,
) -> None:
    """Invalidate (remove) cached wheels for specific packages.

    Pass package names as arguments, or use --all to clear everything.
    """
    if not packages and not invalidate_all:
        raise click.UsageError("Specify package names or use --all.")

    manager = cache.build_cache_manager(wkctx)
    removed = 0

    target_packages = {canonicalize_name(p) for p in packages} if packages else None

    # Only mutate the store backend. Lookup backends may include
    # in-progress build wheels and user-supplied prebuilts.
    backend = manager.store_backend
    keys_to_remove = []
    for key, info in backend.items():
        if target_packages and key.package not in target_packages:
            continue
        keys_to_remove.append((key, info))

    for _key, info in keys_to_remove:
        file_path = pathlib.Path(info.url_or_path)
        if file_path.exists():
            file_path.unlink()
            logger.info("removed %s", file_path)
        removed += 1

    # Re-scan after removing files to update the index
    if keys_to_remove:
        backend.scan()

    click.echo(f"Invalidated {removed} cached artifact(s).")


@cache_cli.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be removed without actually deleting.",
)
@click.option(
    "--keep-latest",
    type=click.IntRange(min=0),
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
    manager = cache.build_cache_manager(wkctx)
    removed = 0
    freed_bytes = 0

    # Only mutate the store backend. Lookup backends may include
    # in-progress build wheels and user-supplied prebuilts.
    backend = manager.store_backend

    # Group by (package, version)
    groups: dict[
        tuple[str, str], list[tuple[cache.WheelCacheKey, cache.ArtifactInfo]]
    ] = {}
    for key, info in backend.items():
        group_key = (str(key.package), str(key.version))
        groups.setdefault(group_key, []).append((key, info))

    needs_rescan = False
    for _group_key, entries in groups.items():
        if len(entries) <= keep_latest:
            continue

        # Prefer higher build tags; break ties (including untagged) by mtime
        # so --keep-latest retains the newest file on disk.
        def _gc_sort_key(
            entry: tuple[cache.WheelCacheKey, cache.ArtifactInfo],
        ) -> tuple[int, float]:
            key, info = entry
            tag_num = key.build_tag[0] if key.build_tag else 0
            try:
                mtime = pathlib.Path(info.url_or_path).stat().st_mtime
            except OSError:
                mtime = 0.0
            return (tag_num, mtime)

        entries.sort(key=_gc_sort_key, reverse=True)
        to_remove = entries[keep_latest:]

        for _key, info in to_remove:
            file_path = pathlib.Path(info.url_or_path)
            size = info.size_bytes or 0
            if dry_run:
                click.echo(f"  would remove: {info.filename} ({_format_size(size)})")
            else:
                if file_path.exists():
                    file_path.unlink()
                needs_rescan = True
                logger.info("gc removed %s", file_path)
            removed += 1
            freed_bytes += size

    if needs_rescan:
        backend.scan()

    verb = "Would remove" if dry_run else "Removed"
    click.echo(f"{verb} {removed} old build(s), freeing {_format_size(freed_bytes)}.")


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes == 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
