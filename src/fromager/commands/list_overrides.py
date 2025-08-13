import csv
import json
import pathlib
import sys

import click
import rich
from packaging.version import Version
from rich.table import Table

from fromager import clickext, context
from fromager.packagesettings import PatchMap


@click.command()
@click.option(
    "--details",
    is_flag=True,
    default=False,
    help="Show more details about the overrides.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "csv", "json"], case_sensitive=False),
    default="table",
    help="Output format for detailed view (requires --details, default: table)",
)
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    help="Output file to create (requires --details, default: stdout)",
)
@click.pass_obj
def list_overrides(
    wkctx: context.WorkContext,
    details: bool,
    output_format: str,
    output: pathlib.Path | None,
) -> None:
    """List all of the packages with overrides in the current configuration."""
    # Warn if format/output options are used without --details
    if not details:
        if output_format != "table":
            click.echo(
                "Warning: --format option is ignored when --details is not used",
                err=True,
            )
        if output is not None:
            click.echo(
                "Warning: --output option is ignored when --details is not used",
                err=True,
            )

    overridden_packages = sorted(wkctx.settings.list_overrides())
    if not details:
        for name in overridden_packages:
            print(name)
        return

    # Collect data for export
    variants = sorted(wkctx.settings.all_variants())
    variant_names = [str(v) for v in variants]
    export_data = []

    for name in overridden_packages:
        pbi = wkctx.settings.package_build_info(name)
        ps = wkctx.settings.package_setting(name)

        plugin_hooks: list[str] = []
        if pbi.plugin:
            for hook in [
                # from hooks.py
                "post_build",
                "post_bootstrap",
                "prebuilt_wheel",
                # from overrides.py, found by searching for find_override_method
                "download_source",
                "resolve_source",
                "get_resolver_provider",
                "prepare_source",
                "build_sdist",
                "build_wheel",
                "get_build_requirements",
                "get_build_sdist_requirements",
                "get_build_wheel_requirements",
                "expected_source_archive_name",
                "expected_source_directory_name",
                "add_extra_metadata_to_wheels",
            ]:
                if hasattr(pbi.plugin, hook):
                    plugin_hooks.append(hook)
        plugin_hooks_str = ", ".join(plugin_hooks)

        variant_info: dict[str, str] = {}
        for v in variants:
            v_info = ps.variants.get(v)
            if v_info:
                if v_info.pre_built:
                    variant_info[str(v)] = "pre-built"
                else:
                    variant_info[str(v)] = "yes"
            else:
                variant_info[str(v)] = ""

        all_patches: PatchMap = pbi.get_all_patches()
        global_patches: list[pathlib.Path] = all_patches.get(None, [])
        num_global_patches: int = len(global_patches)

        all_pkg_versions: list[Version] = sorted(
            [v for v in all_patches.keys() if v is not None]
        )

        if not all_pkg_versions:
            # This package has overrides, but none are version-specific.
            patches_str = str(num_global_patches) if num_global_patches else ""
            row_data = {
                "package": name,
                "version": "",
                "patches": patches_str,
                "plugin_hooks": plugin_hooks_str,
            }
            # Add variant information
            row_data.update(variant_info)
            export_data.append(row_data)
        else:
            # This package has version-specific overrides.
            for version in all_pkg_versions:
                version_patches: list[pathlib.Path] = all_patches.get(version, [])
                total_patches: int = num_global_patches + len(version_patches)
                patches_str = str(total_patches) if total_patches else ""

                row_data = {
                    "package": name,
                    "version": str(version),
                    "patches": patches_str,
                    "plugin_hooks": plugin_hooks_str,
                }
                # Add variant information
                row_data.update(variant_info)
                export_data.append(row_data)

    # Handle different output formats
    match output_format:
        case "json":
            _export_json(export_data, output)
        case "csv":
            _export_csv(export_data, variant_names, output)
        case "table":
            _export_table(export_data, variant_names)
        case _:
            raise ValueError(f"Invalid output format: {output_format}")


def _export_json(data: list[dict], output: pathlib.Path | None) -> None:
    """Export data as JSON."""
    if output:
        with open(output, "w") as outfile:
            json.dump(data, outfile, indent=2)
    else:
        json.dump(data, sys.stdout, indent=2)


def _export_csv(
    data: list[dict], variants: list[str], output: pathlib.Path | None
) -> None:
    """Export data as CSV."""
    # Define field names in the order we want them
    fieldnames = ["package", "version", "patches"] + variants + ["plugin_hooks"]

    if output:
        with open(output, "w", newline="") as outfile:
            writer = csv.DictWriter(
                outfile, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC
            )
            writer.writeheader()
            writer.writerows(data)
    else:
        writer = csv.DictWriter(
            sys.stdout, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC
        )
        writer.writeheader()
        writer.writerows(data)


def _export_table(data: list[dict], variants: list[str]) -> None:
    """Export data as Rich table (original behavior)."""
    table = Table(title="Package Overrides")
    table.add_column("Package", justify="left", no_wrap=True)
    table.add_column("Version", justify="left", no_wrap=True)
    table.add_column("Patches", justify="left", no_wrap=True)

    for v in variants:
        table.add_column(v, justify="left", no_wrap=True)

    table.add_column("Plugin", justify="left")

    # Define column keys in the same order as CSV exporter
    column_keys = ["package", "version", "patches"] + variants + ["plugin_hooks"]

    for row_data in data:
        row = [row_data.get(key, "") for key in column_keys]
        table.add_row(*row)

    rich.get_console().print(table)
