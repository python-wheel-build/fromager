#!/usr/bin/env python3

import logging
import pathlib

import click

from . import clickext, commands, context, overrides, settings

logger = logging.getLogger(__name__)

TERSE_LOG_FMT = "%(message)s"
VERBOSE_LOG_FMT = "%(levelname)s:%(name)s:%(lineno)d: %(message)s"


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
    help="location of environment override files",
)
@click.option(
    "--settings-file",
    default=pathlib.Path("overrides/settings.yaml"),
    type=clickext.ClickPath(),
    help="location of the application settings file",
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
@click.pass_context
def main(
    ctx,
    verbose: bool,
    log_file: pathlib.Path,
    sdists_repo: pathlib.Path,
    wheels_repo: pathlib.Path,
    work_dir: pathlib.Path,
    patches_dir: pathlib.Path,
    envs_dir: pathlib.Path,
    settings_file: pathlib.Path,
    wheel_server_url: str,
    cleanup: bool,
    variant: str,
):
    # Configure console and log output.
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_formatter = logging.Formatter(VERBOSE_LOG_FMT if verbose else TERSE_LOG_FMT)
    stream_handler.setFormatter(stream_formatter)
    logging.getLogger().addHandler(stream_handler)
    if log_file:
        # Always log to the file at debug level
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(VERBOSE_LOG_FMT)
        file_handler.setFormatter(file_formatter)
        logging.getLogger().addHandler(file_handler)
    # We need to set the overall logger level to debug and allow the
    # handlers to filter messages at their own level.
    logging.getLogger().setLevel(logging.DEBUG)

    overrides.log_overrides()

    wkctx = context.WorkContext(
        active_settings=settings.load(settings_file),
        patches_dir=patches_dir,
        envs_dir=envs_dir,
        sdists_repo=sdists_repo,
        wheels_repo=wheels_repo,
        work_dir=work_dir,
        wheel_server_url=wheel_server_url,
        cleanup=cleanup,
        variant=variant,
    )
    wkctx.setup()
    ctx.obj = wkctx


for cmd in commands.commands:
    main.add_command(cmd)


def invoke_main():
    # Wrapper for the click main command that ensures any exceptions
    # are logged so that build pipeline outputs include the traceback.
    try:
        main(auto_envvar_prefix="FROMAGER")
    except Exception as err:
        logger.exception(err)
        raise


if __name__ == "__main__":
    invoke_main()
