import concurrent.futures
import json
import pathlib
import subprocess
import typing
from unittest.mock import Mock, patch

import click
import pytest
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import bootstrapper, packagesettings, sources, wheels
from fromager.bootstrapper._cache import bg_prepare_prebuilt
from fromager.bootstrapper._prepare_source import PrepareSource
from fromager.bootstrapper._process_install_deps import ProcessInstallDeps
from fromager.bootstrapper._start import Start
from fromager.bootstrapper._work_item import WorkItem
from fromager.commands import bootstrap, build, download_sequence, step
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType, SourceType


def _configure_package(ctx: WorkContext, yaml_str: str) -> None:
    """Apply one package setting to the test context."""
    ps = packagesettings.PackageSettings.from_string("pkg", yaml_str)
    ctx.settings._package_settings[ps.name] = ps


@pytest.mark.parametrize("provider", ["pypi-prebuilt", "hook-prebuilt"])
def test_bootstrap_prebuilt_uses_configured_download(
    tmp_context: WorkContext, provider: str
) -> None:
    """Bootstrap consumes the configured wheel path and updates its mirror."""
    _configure_package(tmp_context, f"source:\n  provider: {provider}\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(wheels, "download_prebuilt_wheel", return_value=wheel) as download,
        patch("fromager.bootstrapper._cache.server.update_wheel_mirror") as mirror,
    ):
        result = bg_prepare_prebuilt(
            tmp_context, req, RequirementType.TOP_LEVEL, version, url
        )

    assert result.wheel_filename == wheel
    download.assert_called_once_with(
        ctx=tmp_context, req=req, version=version, download_url=url
    )
    mirror.assert_called_once_with(tmp_context)


def test_bootstrap_configured_prebuilt_reuses_local_wheel(
    tmp_context: WorkContext,
) -> None:
    """A local wheel cache hit bypasses the configured download hook."""
    _configure_package(tmp_context, "source:\n  provider: hook-prebuilt\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    tmp_context.wheel_server_url = "https://local.test/simple/"
    url = "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(wheels, "download_prebuilt_wheel") as configured,
        patch.object(wheels, "download_wheel", return_value=wheel) as cached,
        patch("fromager.bootstrapper._cache.server.update_wheel_mirror"),
    ):
        result = bg_prepare_prebuilt(
            tmp_context, req, RequirementType.TOP_LEVEL, version, url
        )

    assert result.wheel_filename == wheel
    cached.assert_called_once_with(req, url, tmp_context.wheels_prebuilt)
    configured.assert_not_called()


@pytest.mark.parametrize("local_cache", [False, True])
def test_bootstrap_prebuilt_rejects_source_only_resolver(
    tmp_context: WorkContext, local_cache: bool
) -> None:
    """Do not treat a configured sdist resolver as a legacy wheel source."""
    _configure_package(tmp_context, "source:\n  provider: pypi-sdist\n")
    req = Requirement("pkg==1.0")
    if local_cache:
        tmp_context.wheel_server_url = "https://local.test/simple/"
    url = (
        "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl"
        if local_cache
        else "https://pkg.test/pkg-1.0-py3-none-any.whl"
    )
    with (
        patch.object(wheels, "download_prebuilt_wheel") as configured,
        patch("fromager.bootstrapper._cache.wheels.download_wheel") as legacy,
        pytest.raises(ValueError, match="does not resolve prebuilt wheels"),
    ):
        bg_prepare_prebuilt(
            tmp_context,
            req,
            RequirementType.TOP_LEVEL,
            Version("1.0"),
            url,
        )

    configured.assert_not_called()
    legacy.assert_not_called()


@pytest.mark.parametrize("provider", ["pypi-prebuilt", "hook-prebuilt"])
def test_build_order_replay_uses_configured_download(
    tmp_context: WorkContext, provider: str
) -> None:
    """A later build run selects the configured wheel download contract."""
    _configure_package(tmp_context, f"source:\n  provider: {provider}\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(build, "_is_wheel_built", return_value=None),
        patch.object(wheels, "download_prebuilt_wheel", return_value=wheel) as download,
        patch.object(build.wheels, "download_wheel") as legacy,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks") as hooks,
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(tmp_context, version, req, url, False, None)

    assert result.prebuilt is True
    assert result.wheel_filename == wheel
    download.assert_called_once_with(
        ctx=tmp_context, req=req, version=version, download_url=url
    )
    legacy.assert_not_called()
    hooks.assert_called_once()


def test_configured_prebuilt_reuses_cached_wheel(tmp_context: WorkContext) -> None:
    """A cache hit avoids a fresh resolver download while retaining hooks."""
    _configure_package(tmp_context, "source:\n  provider: hook-prebuilt\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    cached = tmp_context.wheels_downloads / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(build, "_is_wheel_built", return_value=cached),
        patch.object(wheels, "download_prebuilt_wheel") as download,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks") as hooks,
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(tmp_context, version, req, url, False, None)

    assert result.wheel_filename == cached
    assert result.skipped is True
    download.assert_not_called()
    hooks.assert_called_once()


def test_download_sequence_replays_configured_prebuilt(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """Download sequence uses the saved URL with the selected source resolver."""
    _configure_package(tmp_context, "source:\n  provider: hook-prebuilt\n")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [{"dist": "pkg", "version": "1.0", "prebuilt": True, "source_url": url}]
        )
    )
    with (
        patch.object(wheels, "download_prebuilt_wheel") as download,
        patch.object(download_sequence.wheels, "download_wheel") as legacy,
    ):
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [
                str(build_order),
                "https://index.test/simple",
                "--include-wheels",
                "--num-threads",
                "1",
            ],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    download.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        download_url=url,
    )
    legacy.assert_not_called()


def test_download_sequence_rejects_stale_prebuilt_flag(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """A source-only resolver cannot replay a prebuilt build-order entry."""
    _configure_package(tmp_context, "source:\n  provider: pypi-sdist\n")
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": True,
                    "source_url": "https://pkg.test/pkg-1.0-py3-none-any.whl",
                }
            ]
        )
    )
    with (
        patch.object(wheels, "download_prebuilt_wheel") as configured,
        patch.object(download_sequence.wheels, "download_wheel") as legacy,
    ):
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [
                str(build_order),
                "https://index.test/simple",
                "--include-wheels",
                "--num-threads",
                "1",
            ],
            obj=tmp_context,
        )

    assert isinstance(result.exception, ValueError)
    assert "does not resolve prebuilt wheels" in str(result.exception)
    configured.assert_not_called()
    legacy.assert_not_called()


def test_legacy_prebuilt_keeps_direct_download(tmp_context: WorkContext) -> None:
    """Legacy pre_built still downloads into the build wheel directory."""
    _configure_package(tmp_context, "variants:\n  cpu:\n    pre_built: true\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_build / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(build, "_is_wheel_built", return_value=None),
        patch.object(build.wheels, "download_wheel", return_value=wheel) as legacy,
        patch.object(wheels, "download_prebuilt_wheel") as configured,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks"),
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(tmp_context, version, req, url, False, None)

    assert result.prebuilt is True
    assert result.wheel_filename == tmp_context.wheels_downloads / wheel.name
    legacy.assert_called_once_with(
        req=req, wheel_url=url, output_directory=tmp_context.wheels_build
    )
    configured.assert_not_called()


def test_legacy_bootstrap_keeps_direct_download(tmp_context: WorkContext) -> None:
    """Legacy bootstrap still uses the wheel downloader."""
    _configure_package(tmp_context, "variants:\n  cpu:\n    pre_built: true\n")
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch(
            "fromager.bootstrapper._cache.wheels.download_wheel", return_value=wheel
        ) as legacy,
        patch.object(wheels, "download_prebuilt_wheel") as configured,
        patch("fromager.bootstrapper._cache.server.update_wheel_mirror"),
    ):
        result = bg_prepare_prebuilt(
            tmp_context, req, RequirementType.TOP_LEVEL, version, url
        )

    assert result.wheel_filename == wheel
    legacy.assert_called_once_with(req, url, tmp_context.wheels_prebuilt)
    configured.assert_not_called()


@pytest.mark.parametrize("provider", ["pypi-prebuilt", "hook-prebuilt"])
def test_bootstrap_records_configured_prebuilt_in_graph_and_order(
    tmp_context: WorkContext, provider: str
) -> None:
    """The selected source makes bootstrap skip build phases and persist its flag."""
    _configure_package(tmp_context, f"source:\n  provider: {provider}\n")
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    with patch.object(bt, "resolve_versions", return_value=[(url, version)]):
        bt._resolve_and_add_top_level(req)

    wi = WorkItem(
        req=req,
        req_type=RequirementType.TOP_LEVEL,
        why_snapshot=[],
        source_url=url,
        resolved_version=version,
    )
    next_phases = Start(wi).run(bt)
    assert wi.pbi_pre_built is True
    assert len(next_phases) == 1
    assert isinstance(next_phases[0], PrepareSource)
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(wheels, "download_prebuilt_wheel", return_value=wheel),
        patch.object(sources, "prepare_source") as prepare_source,
        patch("fromager.bootstrapper._cache.server.update_wheel_mirror"),
    ):
        background_work = next_phases[0].background_work(bt)
        assert background_work is not None
        prepared = background_work()
    prepare_source.assert_not_called()
    future: concurrent.futures.Future[typing.Any] = concurrent.futures.Future()
    future.set_result(prepared)
    next_phases[0].bg_future = future
    install_phases = next_phases[0].run(bt)
    assert len(install_phases) == 1
    assert isinstance(install_phases[0], ProcessInstallDeps)
    assert wi.build_result is not None
    assert wi.build_result.source_type is SourceType.PREBUILT
    with (
        patch(
            "fromager.bootstrapper._process_install_deps.hooks.run_post_bootstrap_hooks"
        ),
        patch(
            "fromager.bootstrapper._process_install_deps._get_install_dependencies",
            return_value=[],
        ),
        patch.object(bt, "create_unresolved_work_items", return_value=[]),
    ):
        install_phases[0].run(bt)
    bt.finalize()

    assert tmp_context.dependency_graph.nodes["pkg==1.0"].pre_built is True
    build_order = json.loads(bt._build_order_filename.read_text())
    assert build_order[0]["prebuilt"] is True
    assert build_order[0]["source_url"] == url


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
