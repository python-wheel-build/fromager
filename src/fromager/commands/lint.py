import logging

import click

from .. import context, overrides

logger = logging.getLogger(__name__)


@click.command()
@click.pass_obj
def lint(
    wkctx: context.WorkContext,
) -> None:
    """Review existing settings and overrides for potential configuration errors."""
    errors = 0

    logger.info(f"Checking patches in {wkctx.settings.patches_dir}...")
    for entry in wkctx.settings.patches_dir.glob("*"):
        logger.debug(entry)
        if "-" in entry.name:
            actual_package_name, _, version_str = entry.name.rpartition("-")
            expected_package_name = overrides.pkgname_to_override_module(
                actual_package_name
            )
            if actual_package_name != expected_package_name:
                errors += 1
                logger.error(
                    f"ERROR: Patch directory {entry.name} should be {expected_package_name}-{version_str}"
                )
        else:
            expected_package_name = overrides.pkgname_to_override_module(entry.name)
            if actual_package_name != expected_package_name:
                errors += 1
                logger.error(
                    f"ERROR: Patch directory {entry.name} should be {expected_package_name}"
                )

    if wkctx.settings_dir is not None:
        logger.info(f"Checking settings files in {wkctx.settings_dir}...")
        for entry in wkctx.settings_dir.glob("*"):
            logger.debug(entry)
            if entry.suffix != ".yaml":
                errors += 1
                logger.error(
                    f"ERROR: settings file {entry.name} should use extension '.yaml'"
                )
            expected_package_name = overrides.pkgname_to_override_module(entry.stem)
            if entry.stem != expected_package_name:
                errors += 1
                logger.error(
                    f"ERROR: Settings file {entry.name} should be {expected_package_name}.yaml"
                )

    logger.info("Checking entry points...")
    exts = overrides._get_extensions()
    for name in exts.names():
        logger.debug(name)
        expected_name = overrides.pkgname_to_override_module(name)
        if name != expected_name:
            errors += 1
            logger.error(f"ERROR: plugin name {name} should be {expected_name}")

    if errors:
        raise SystemExit(f"Found {errors} errors")
