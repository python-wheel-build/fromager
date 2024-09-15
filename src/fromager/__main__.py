#!/usr/bin/env python3

import logging
import pathlib

import click

from . import (
    clickext,
    commands,
    context,
    external_commands,
    overrides,
    packagesettings,
)

logger = logging.getLogger(__name__)

TERSE_LOG_FMT = "%(message)s"
VERBOSE_LOG_FMT = "%(levelname)s:%(name)s:%(lineno)d: %(message)s"

try:
    external_commands.detect_network_isolation()
except Exception as e:
    SUPPORTS_NETWORK_ISOLATION: bool = False
    NETWORK_ISOLATION_ERROR: str | None = str(e)
else:
    SUPPORTS_NETWORK_ISOLATION = True
    NETWORK_ISOLATION_ERROR = None


@click.group()
@click.option(
    "-v",
    "--verbose",
    default=False,
    is_flag=True,
    help="report more detail to the console",
)
@click.option(
    "--log-file",
    type=clickext.ClickPath(),
    help="save detailed report of actions to file",
)
@click.option(
    "--error-log-file",
    type=clickext.ClickPath(),
    help="save error messages to a file",
)
@click.option(
    "-o",
    "--sdists-repo",
    default=pathlib.Path("sdists-repo"),
    type=clickext.ClickPath(),
    help="location to manage source distributions",
)
@click.option(
    "-w",
    "--wheels-repo",
    default=pathlib.Path("wheels-repo"),
    type=clickext.ClickPath(),
    help="location to manage wheel repository",
)
@click.option(
    "-t",
    "--work-dir",
    default=pathlib.Path("work-dir"),
    type=clickext.ClickPath(),
    help="location to manage working files, including builds",
)
@click.option(
    "-p",
    "--patches-dir",
    default=pathlib.Path("overrides/patches"),
    type=clickext.ClickPath(),
    help="location of files for patching source before building",
)
@click.option(
    "-e",
    "--envs-dir",
    default=pathlib.Path("overrides/envs"),
    type=clickext.ClickPath(),
    help="deprecated: no longer used",
    hidden=True,
    expose_value=False,
)
@click.option(
    "--settings-file",
    default=pathlib.Path("overrides/settings.yaml"),
    type=clickext.ClickPath(),
    help="location of the application settings file",
)
@click.option(
    "--settings-dir",
    default=pathlib.Path("overrides/settings"),
    type=clickext.ClickPath(),
    help="location of per-package settings files",
)
@click.option(
    "-c",
    "--constraints-file",
    type=clickext.ClickPath(),
    help="location of the constraints file",
)
@click.option(
    "--wheel-server-url",
    default="",
    type=str,
    help="URL for the wheel server for builds",
)
@click.option(
    "--cleanup/--no-cleanup",
    default=True,
    help="control removal of working files when a build completes successfully",
)
@click.option("--variant", default="cpu", help="the build variant name")
@click.option(
    "-j",
    "--jobs",
    type=int,
    default=None,
    help="maximum number of jobs to run in parallel",
)
@click.option(
    "--network-isolation/--no-network-isolation",
    default=SUPPORTS_NETWORK_ISOLATION,
    help="Build sdist and wheen with network isolation (unshare -cn)",
    show_default=True,
)
@click.pass_context
def main(
    ctx: click.Context,
    verbose: bool,
    log_file: pathlib.Path,
    error_log_file: pathlib.Path,
    sdists_repo: pathlib.Path,
    wheels_repo: pathlib.Path,
    work_dir: pathlib.Path,
    patches_dir: pathlib.Path,
    settings_file: pathlib.Path,
    settings_dir: pathlib.Path,
    constraints_file: pathlib.Path,
    wheel_server_url: str,
    cleanup: bool,
    variant: str,
    jobs: int | None,
    network_isolation: bool,
) -> None:
    # Set the overall logger level to debug and allow the handlers to filter
    # messages at their own level.
    logging.getLogger().setLevel(logging.DEBUG)
    # Configure a stream handler for console messages at the requested verbosity
    # level.
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_formatter = logging.Formatter(VERBOSE_LOG_FMT if verbose else TERSE_LOG_FMT)
    stream_handler.setFormatter(stream_formatter)
    logging.getLogger().addHandler(stream_handler)
    # If we're given an error log file, configure a file handler for all error
    # messages to make them easier to find without sifting through the full
    # debug log.
    if error_log_file:
        error_handler = logging.FileHandler(error_log_file)
        error_handler.setLevel(logging.ERROR)
        error_formatter = logging.Formatter(VERBOSE_LOG_FMT)
        error_handler.setFormatter(error_formatter)
        logging.getLogger().addHandler(error_handler)
    # If we're given a debug log filename, configure the file handler.
    if log_file:
        # Always log to the file at debug level
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(VERBOSE_LOG_FMT)
        file_handler.setFormatter(file_formatter)
        logging.getLogger().addHandler(file_handler)
        logger.info("logging debug information to %s", log_file)
    # Report the error log file after configuring the debug log file so the
    # message is saved to the debug log.
    if error_log_file:
        logger.info("logging errors to %s", error_log_file)

    logger.info(f"primary settings file: {settings_file}")
    logger.info(f"per-package settings dir: {settings_dir}")
    logger.info(f"variant: {variant}")
    logger.info(f"patches dir: {patches_dir}")
    logger.info(f"maximum concurrent jobs: {jobs}")
    logger.info(f"constraints file: {constraints_file}")
    logger.info(f"wheel server url: {wheel_server_url}")
    logger.info(f"network isolation: {network_isolation}")
    overrides.log_overrides()

    if network_isolation and not SUPPORTS_NETWORK_ISOLATION:
        ctx.fail(f"network isolation is not available: {NETWORK_ISOLATION_ERROR}")

    wkctx = context.WorkContext(
        active_settings=packagesettings.Settings.from_files(
            settings_file=settings_file,
            settings_dir=settings_dir,
            patches_dir=patches_dir,
            variant=variant,
            max_jobs=jobs,
        ),
        constraints_file=constraints_file,
        patches_dir=patches_dir,
        sdists_repo=sdists_repo,
        wheels_repo=wheels_repo,
        work_dir=work_dir,
        wheel_server_url=wheel_server_url,
        cleanup=cleanup,
        variant=variant,
        network_isolation=network_isolation,
        max_jobs=jobs,
        settings_dir=settings_dir,
    )
    wkctx.setup()
    ctx.obj = wkctx


for cmd in commands.commands:
    main.add_command(cmd)


def invoke_main() -> None:
    # Wrapper for the click main command that ensures any exceptions
    # are logged so that build pipeline outputs include the traceback.
    try:
        main(auto_envvar_prefix="FROMAGER")
    except Exception as err:
        logger.exception(err)
        raise


if __name__ == "__main__":
    invoke_main()
