import click
import rich
from rich.table import Table

from fromager import context


@click.command()
@click.option(
    "--details",
    is_flag=True,
    default=False,
    help="Show more details about the overrides.",
)
@click.pass_obj
def list_overrides(
    wkctx: context.WorkContext,
    details: bool,
) -> None:
    """List all of the packages with overrides in the current configuration."""
    overridden_packages = sorted(wkctx.settings.list_overrides())
    if not details:
        for name in overridden_packages:
            print(name)
        return

    table = Table(title="Package Overrides")
    table.add_column("Package", justify="left", no_wrap=True)
    table.add_column("Version", justify="left", no_wrap=True)
    table.add_column("Patches", justify="left", no_wrap=True)
    table.add_column("Plugin", justify="left")

    variants = sorted(wkctx.settings.all_variants())
    for v in variants:
        table.add_column(v, justify="left", no_wrap=True)

    for name in overridden_packages:
        pbi = wkctx.settings.package_build_info(name)
        ps = wkctx.settings.package_setting(name)

        plugin_hooks = []
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

        variant_info = []
        for v in variants:
            v_info = ps.variants.get(v)
            if v_info:
                if v_info.pre_built:
                    variant_info.append("pre-built")
                else:
                    variant_info.append("yes")
            else:
                variant_info.append("")

        all_patches = pbi.get_all_patches()
        global_patches = all_patches.get(None, [])
        num_global_patches = len(global_patches)

        all_pkg_versions = sorted([v for v in all_patches.keys() if v is not None])

        if not all_pkg_versions:
            # This package has overrides, but none are version-specific.
            patches_str = str(num_global_patches) if num_global_patches else ""
            row = [
                name,
                "",  # Version
                patches_str,
                plugin_hooks_str,
            ] + variant_info
            table.add_row(*row)
        else:
            # This package has version-specific overrides.
            for version in all_pkg_versions:
                version_patches = all_patches.get(version, [])
                total_patches = num_global_patches + len(version_patches)
                patches_str = str(total_patches) if total_patches else ""

                row = [
                    name,
                    str(version),
                    patches_str,
                    plugin_hooks_str,
                ] + variant_info
                table.add_row(*row)

    rich.get_console().print(table)
