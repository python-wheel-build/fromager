import pathlib
import typing
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import packagesettings
from fromager.commands import bootstrap, build, step
from fromager.context import WorkContext


def get_option_names(cmd: click.Command) -> typing.Iterable[str]:
    return [o.name for o in cmd.params if o.name]


def test_bootstrap_parallel_options() -> None:
    expected: set[str] = set()
    expected.update(get_option_names(bootstrap.bootstrap))
    expected.update(get_option_names(build.build_parallel))
    # bootstrap-parallel enforces sdist_only=True and handles
    # graph_file internally.
    expected.discard("sdist_only")
    expected.discard("graph_file")
    expected.discard("test_mode")

    assert set(get_option_names(bootstrap.bootstrap_parallel)) == expected


def test_download_source_archive_prints_downloaded_path(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """Print only the path when the download helper returns a tuple."""
    expected = tmp_path / "pkg-1.0.tar.gz"

    with (
        patch.object(
            step.sources,
            "resolve_source",
            return_value=("https://pkg.test/pkg-1.0.tar.gz", Version("1.0")),
        ),
        patch.object(
            step.sources,
            "download_source",
            return_value=(expected, packagesettings.DownloadKind.sdist),
        ),
    ):
        result = cli_runner.invoke(
            step.step,
            [
                "download-source-archive",
                "pkg",
                "1.0",
                "https://pkg.test/simple",
            ],
            obj=tmp_context,
        )

    assert result.exit_code == 0
    assert result.output == f"{expected}\n"


def test_build_passes_downloaded_path_to_prepare_source(
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """Pass only the downloaded path into source preparation."""
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    source_url = "https://pkg.test/pkg-1.0.tar.gz"
    source_filename = tmp_path / "pkg-1.0.tar.gz"
    source_root = tmp_path / "pkg-1.0"
    sdist_filename = tmp_path / "rebuilt" / "pkg-1.0.tar.gz"
    wheel_filename = tmp_path / "pkg-1.0-py3-none-any.whl"
    build_env = Mock()

    with (
        patch.object(build.wheels, "get_wheel_server_urls", return_value=[]),
        patch.object(
            build.sources,
            "download_source",
            return_value=(source_filename, packagesettings.DownloadKind.sdist),
        ),
        patch.object(
            build.sources,
            "prepare_source",
            return_value=source_root,
        ) as prepare_source,
        patch.object(
            build.build_environment,
            "prepare_build_environment",
            return_value=build_env,
        ),
        patch.object(build.sources, "build_sdist", return_value=sdist_filename),
        patch.object(build.wheels, "build_wheel", return_value=wheel_filename),
        patch.object(build.hooks, "run_post_build_hooks"),
        patch.object(tmp_context, "clean_build_dirs"),
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(
            wkctx=tmp_context,
            resolved_version=version,
            req=req,
            source_download_url=source_url,
            force=True,
            cache_wheel_server_url=None,
        )

    prepare_source.assert_called_once_with(
        ctx=tmp_context,
        req=req,
        source_filename=source_filename,
        version=version,
    )
    assert result.wheel_filename == tmp_context.wheels_downloads / wheel_filename.name
