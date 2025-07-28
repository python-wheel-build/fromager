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
    table.add_column("Patches", justify="left", no_wrap=True)
    table.add_column("Plugin", justify="left")
    table.add_column("Pre-built", justify="left", no_wrap=True)

    variants = sorted(wkctx.settings.all_variants())
    for v in variants:
        table.add_column(v, justify="left", no_wrap=True)

    for name in overridden_packages:
        pbi = wkctx.settings.package_build_info(name)
        has_patches = "yes" if pbi.get_all_patches() else ""
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
        is_prebuilt = "yes" if pbi.pre_built else ""

        row = [
            name,
            has_patches,
            ", ".join(plugin_hooks),
            is_prebuilt,
        ]
        for v in variants:
            row.append("yes" if v in pbi.variants else "")
        table.add_row(*row)

    rich.get_console().print(table)
