import json
import pathlib
import subprocess
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
    """Keep the path-only output for existing scripts."""
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
            return_value=packagesettings.DownloadedSource(
                path=expected, kind=packagesettings.DownloadKind.sdist
            ),
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


def test_download_source_archive_json_includes_kind(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    checkout = tmp_path / "pkg-1.0"

    with (
        patch.object(
            step.sources,
            "resolve_source",
            return_value=("git+https://code.test/pkg.git@v1.0", Version("1.0")),
        ),
        patch.object(
            step.sources,
            "download_source",
            return_value=packagesettings.DownloadedSource(
                checkout, packagesettings.DownloadKind.git_checkout
            ),
        ),
    ):
        result = cli_runner.invoke(
            step.step,
            [
                "download-source-archive",
                "--output-format",
                "json",
                "pkg",
                "1.0",
                "https://pkg.test/simple",
            ],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "path": str(checkout),
        "kind": "git_checkout",
    }


def test_step_prepare_source_prepares_clean_git_checkout(
    cli_runner: CliRunner, tmp_context: WorkContext
) -> None:
    checkout = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
    checkout.mkdir(parents=True)
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)

    with patch.object(step.sources, "prepare_new_source") as prepare_new_source:
        result = cli_runner.invoke(
            step.step,
            ["prepare-source", "--source-kind", "git_checkout", "pkg", "1.0"],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    assert result.output == f"{checkout}\n"
    prepare_new_source.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        source_root_dir=checkout,
        version=Version("1.0"),
    )
    assert (checkout.parent / "build-meta.json").is_file()


def test_step_prepare_source_kind_selects_checkout_over_archive(
    cli_runner: CliRunner, tmp_context: WorkContext
) -> None:
    archive = tmp_context.sdists_downloads / "pkg-1.0.tar.gz"
    archive.write_bytes(b"old archive")
    checkout = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
    checkout.mkdir(parents=True)
    with patch.object(
        step.sources, "prepare_source", return_value=checkout
    ) as prepare_source:
        result = cli_runner.invoke(
            step.step,
            ["prepare-source", "--source-kind", "git_checkout", "pkg", "1.0"],
            obj=tmp_context,
        )

    assert result.exit_code == 0
    assert result.output == f"{checkout}\n"
    prepare_source.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        source_filename=checkout,
        version=Version("1.0"),
        download_kind=packagesettings.DownloadKind.git_checkout,
    )


def test_step_prepare_source_defaults_to_archive_kind(
    cli_runner: CliRunner, tmp_context: WorkContext
) -> None:
    archive = tmp_context.sdists_downloads / "pkg-1.0.tar.gz"
    archive.write_bytes(b"archive")
    checkout = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
    checkout.mkdir(parents=True)

    with patch.object(
        step.sources, "prepare_source", return_value=checkout
    ) as prepare_source:
        result = cli_runner.invoke(
            step.step, ["prepare-source", "pkg", "1.0"], obj=tmp_context
        )

    assert result.exit_code == 0, result.output
    prepare_source.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        source_filename=archive,
        version=Version("1.0"),
        download_kind=packagesettings.DownloadKind.sdist,
    )


def test_step_prepare_source_accepts_explicit_hook_path(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    checkout = tmp_path / "hook-checkout"
    checkout.mkdir()

    with patch.object(
        step.sources, "prepare_source", return_value=checkout
    ) as prepare_source:
        result = cli_runner.invoke(
            step.step,
            [
                "prepare-source",
                "--source-kind",
                "git_checkout",
                "--source-path",
                str(checkout),
                "pkg",
                "1.0",
            ],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    prepare_source.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        source_filename=checkout,
        version=Version("1.0"),
        download_kind=packagesettings.DownloadKind.git_checkout,
    )


def test_step_prepare_source_keeps_archive_inside_cleanup_dir(
    cli_runner: CliRunner, tmp_context: WorkContext
) -> None:
    """Reject an archive that cleanup would delete before opening it."""
    archive = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0.tar.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"original archive")

    result = cli_runner.invoke(
        step.step,
        ["prepare-source", "--source-path", str(archive), "pkg", "1.0"],
        obj=tmp_context,
    )

    assert isinstance(result.exception, ValueError)
    assert "overlaps" in str(result.exception)
    assert archive.read_bytes() == b"original archive"


def test_build_passes_downloaded_kind_to_prepare_source(
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """Pass the downloaded path and kind into source preparation."""
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
            return_value=packagesettings.DownloadedSource(
                path=source_filename, kind=packagesettings.DownloadKind.sdist
            ),
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
        download_kind=packagesettings.DownloadKind.sdist,
    )
    assert result.wheel_filename == tmp_context.wheels_downloads / wheel_filename.name
