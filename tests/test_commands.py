import concurrent.futures
import io
import json
import pathlib
import subprocess
import tarfile
import typing
from unittest.mock import Mock, patch

import click
import pytest
import requests_mock
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import packagesettings, server, wheels
from fromager.commands import bootstrap, build, download_sequence, step
from fromager.context import WorkContext
from fromager.log import requirement_ctxvar


def _configure_package(ctx: WorkContext, yaml_str: str) -> None:
    """Apply one package setting to the test context."""
    ps = packagesettings.PackageSettings.from_string("pkg", yaml_str)
    ctx.settings._package_settings[ps.name] = ps


def _source_yaml(provider: str) -> str:
    """Return package settings that select a configured source provider."""
    yaml_str = f"source:\n  provider: {provider}\n"
    if provider == "hook-prebuilt":
        yaml_str += "  index_url: https://index.test/simple\n"
    return yaml_str


@pytest.mark.parametrize("provider", ["pypi-prebuilt", "hook-prebuilt"])
def test_build_order_replay_uses_configured_download(
    tmp_context: WorkContext, provider: str
) -> None:
    """A later build run selects the configured wheel download contract."""
    _configure_package(tmp_context, _source_yaml(provider))
    req = Requirement("pkg==1.0")
    version = Version("1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(build, "_is_wheel_built", return_value=None),
        patch.object(wheels, "download_prebuilt_wheel", return_value=wheel) as download,
        patch.object(build.wheels, "download_wheel") as legacy,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks") as hooks,
        patch.object(build.server, "update_wheel_mirror") as mirror,
    ):
        result = build._build(tmp_context, version, req, url, False, None)

    assert result.prebuilt is True
    assert result.wheel_filename == wheel
    download.assert_called_once_with(
        ctx=tmp_context,
        req=req,
        version=version,
        download_url=url,
        direct_download_directory=tmp_context.wheels_build,
    )
    legacy.assert_not_called()
    hooks.assert_called_once()
    mirror.assert_called_once_with(tmp_context, preferred_prebuilt_wheel=wheel)


def test_build_replay_local_mirror_url_skips_download_hook(
    tmp_context: WorkContext,
) -> None:
    """Build replay downloads a local mirror URL directly and runs wheel hooks."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    tmp_context.wheel_server_url = "https://local.test/simple/"
    req = Requirement("pkg==1.0")
    url = "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl"
    wheel = tmp_context.wheels_build / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(build, "_is_wheel_built", return_value=None),
        patch.object(wheels, "download_wheel", return_value=wheel) as direct,
        patch("fromager.wheels.sources.download_source") as configured,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks") as hooks,
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(tmp_context, Version("1.0"), req, url, False, None)

    assert result.wheel_filename == tmp_context.wheels_downloads / wheel.name
    direct.assert_called_once_with(req, url, tmp_context.wheels_build)
    configured.assert_not_called()
    hooks.assert_called_once()


def test_forced_build_local_mirror_url_uses_mirrored_wheel(
    tmp_context: WorkContext,
) -> None:
    """A forced build uses and keeps serving the exact mirrored file."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")
    wheel_name = "pkg-1.0-py3-none-any.whl"
    served_wheel = tmp_context.wheels_downloads / wheel_name
    served_wheel.write_bytes(b"served wheel")
    server.update_wheel_mirror(tmp_context)
    (tmp_context.wheels_prebuilt / wheel_name).write_bytes(b"other wheel")
    tmp_context.wheel_server_url = "https://local.test/simple/"
    url = f"https://local.test/simple/pkg/{wheel_name}"

    with (
        patch.object(wheels, "download_wheel") as direct,
        patch("fromager.wheels.sources.download_source") as configured,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks"),
    ):
        result = build._build(tmp_context, Version("1.0"), req, url, True, None)

    mirror_wheel = tmp_context.wheel_server_dir / "pkg" / wheel_name
    assert result.wheel_filename == served_wheel
    assert mirror_wheel.resolve() == served_wheel
    assert mirror_wheel.read_bytes() == b"served wheel"
    direct.assert_not_called()
    configured.assert_not_called()


def test_fresh_configured_prebuilt_replaces_old_mirror_entry(
    tmp_context: WorkContext,
) -> None:
    """A forced hook download makes its new wheel visible in the mirror."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")
    wheel_name = "pkg-1.0-py3-none-any.whl"
    old_wheel = tmp_context.wheels_downloads / wheel_name
    old_wheel.write_bytes(b"old wheel")
    server.update_wheel_mirror(tmp_context)

    fresh_wheel = tmp_context.wheels_prebuilt / wheel_name
    fresh_wheel.write_bytes(b"fresh wheel")
    with (
        patch.object(wheels, "download_prebuilt_wheel", return_value=fresh_wheel),
        patch.object(build.hooks, "run_prebuilt_wheel_hooks"),
    ):
        result = build._build(
            tmp_context,
            Version("1.0"),
            req,
            f"https://pkg.test/{wheel_name}",
            True,
            None,
        )

    mirror_wheel = tmp_context.wheel_server_dir / "pkg" / wheel_name
    assert result.wheel_filename == fresh_wheel
    assert mirror_wheel.resolve() == fresh_wheel
    assert mirror_wheel.read_bytes() == b"fresh wheel"
    assert old_wheel.read_bytes() == b"old wheel"

    tmp_context.wheel_server_url = "https://local.test/simple/"
    mirror_url = f"https://local.test/simple/pkg/{wheel_name}"
    with (
        patch.object(
            wheels,
            "resolve_all_cached_wheels",
            return_value=[(mirror_url, Version("1.0"))],
        ),
        patch.object(wheels, "download_wheel") as direct,
    ):
        cached_wheel = build._is_wheel_built(tmp_context, "pkg", Version("1.0"))

    assert cached_wheel == fresh_wheel
    direct.assert_not_called()


def test_configured_prebuilt_reuses_cached_wheel(tmp_context: WorkContext) -> None:
    """A cache hit avoids a fresh resolver download while retaining hooks."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
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
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": True,
                    "source_url": url,
                    "source_provider": "hook-prebuilt",
                }
            ]
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
        direct_download_directory=tmp_context.wheels_prebuilt,
    )
    legacy.assert_not_called()


@pytest.mark.parametrize("include_wheels", [False, True])
def test_download_sequence_checks_prebuilt_provider_before_download(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
    include_wheels: bool,
) -> None:
    """A configured wheel download requires its recorded provider."""
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": True,
                    "source_url": "https://pkg.test/pkg-1.0-py3-none-any.whl",
                    "source_provider": "hook-prebuilt",
                }
            ]
        )
    )
    args = [str(build_order), "https://index.test/simple", "--num-threads", "1"]
    if include_wheels:
        args.append("--include-wheels")

    with patch.object(wheels, "download_prebuilt_wheel") as download:
        result = cli_runner.invoke(
            download_sequence.download_sequence, args, obj=tmp_context
        )

    assert (result.exit_code != 0) is include_wheels
    if include_wheels:
        assert "hook-prebuilt" in str(result.exception)
    download.assert_not_called()


@pytest.mark.parametrize(
    ("settings_yaml", "url"),
    [
        (
            "source:\n  provider: pypi-sdist\n",
            "https://pkg.test/pkg-1.0.tar.gz",
        ),
        (
            "source:\n"
            "  provider: pypi-download\n"
            "  download_url: https://pkg.test/pkg-{version}.tar.gz\n"
            "  download_kind: tarball\n",
            "https://pkg.test/pkg-1.0.tar.gz",
        ),
        (
            "source:\n"
            "  provider: github-tag-download\n"
            "  project_url: https://github.test/org/pkg\n",
            "https://api.github.test/repos/org/pkg/tarball/v1.0",
        ),
        (
            "source:\n"
            "  provider: gitlab-tag-download\n"
            "  project_url: https://gitlab.test/org/pkg\n",
            "https://gitlab.test/org/pkg/-/archive/v1.0/pkg-v1.0.tar.gz",
        ),
    ],
)
def test_download_sequence_prefetches_configured_archives(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
    requests_mock: requests_mock.Mocker,
    settings_yaml: str,
    url: str,
) -> None:
    """A later resolver download reuses the archive prefetched by the command."""
    _configure_package(tmp_context, settings_yaml)
    source_resolver = tmp_context.package_build_info(
        Requirement("pkg==1.0")
    ).source_resolver
    assert source_resolver is not None
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        metadata = b"Name: pkg\nVersion: 1.0\n"
        member = tarfile.TarInfo("pkg-1.0/PKG-INFO")
        member.size = len(metadata)
        tar.addfile(member, io.BytesIO(metadata))
    requests_mock.get(url, content=archive.getvalue())
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": url,
                    "source_url_type": "override",
                    "source_provider": source_resolver.provider,
                }
            ]
        )
    )

    result = cli_runner.invoke(
        download_sequence.download_sequence,
        [str(build_order), "https://index.test/simple", "--num-threads", "1"],
        obj=tmp_context,
    )

    assert result.exit_code == 0, result.output
    repeated = cli_runner.invoke(
        download_sequence.download_sequence,
        [str(build_order), "https://index.test/simple", "--num-threads", "1"],
        obj=tmp_context,
    )
    assert repeated.exit_code == 0, repeated.output
    cached = tmp_context.sdists_downloads / "pkg-1.0.tar.gz"
    assert cached.exists()
    downloaded = source_resolver.download(
        tmp_context, Requirement("pkg==1.0"), Version("1.0"), url
    )
    assert downloaded.path == cached
    assert requests_mock.call_count == 1


def test_download_sequence_calls_configured_git_download(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """A configured Git resolver downloads even with a legacy override label."""
    _configure_package(
        tmp_context,
        "source:\n"
        "  provider: github-tag-git\n"
        "  project_url: https://github.test/org/pkg\n",
    )
    url = "git+https://github.test/org/pkg@v1.0"
    source_resolver = tmp_context.package_build_info(
        Requirement("pkg==1.0")
    ).source_resolver
    assert source_resolver is not None
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": url,
                    "source_url_type": "override",
                    "source_provider": source_resolver.provider,
                }
            ]
        )
    )
    checkout = tmp_context.work_dir / "pkg-1.0" / "pkg-1.0"
    with patch(
        "fromager.downloads.download_git_source", return_value=checkout
    ) as clone:
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [str(build_order), "https://index.test/simple", "--num-threads", "1"],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    clone.assert_called_once_with(destination_dir=checkout, vcs_url=url)


def test_download_sequence_calls_configured_hook_download(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """A hook source uses its normal download result during sequence replay."""
    _configure_package(
        tmp_context, "source:\n  provider: hook-sdist\n  build_sdist: tarball\n"
    )
    url = "https://pkg.test/pkg-1.0.tar.gz"
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": url,
                    "source_url_type": "override",
                    "source_provider": "hook-sdist",
                }
            ]
        )
    )
    calls: list[tuple[Version, str]] = []

    def hook(version: Version, download_url: str) -> packagesettings.DownloadedSource:
        calls.append((version, download_url))
        return packagesettings.DownloadedSource(
            path=tmp_context.work_dir / "pkg-1.0" / "pkg-1.0",
            kind=packagesettings.DownloadKind.git_checkout,
        )

    with patch("fromager.overrides.find_override_method", return_value=hook):
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [str(build_order), "https://index.test/simple", "--num-threads", "1"],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    assert calls == [(Version("1.0"), url)]


def test_download_sequence_keeps_legacy_sdist_selection(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """Old build-order entries still prefetch through the legacy downloader."""
    url = "https://pkg.test/pkg-1.0.tar.gz"
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": url,
                    "source_url_type": "sdist",
                }
            ]
        )
    )
    with patch.object(download_sequence.sources, "download_source") as download:
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [str(build_order), "https://index.test/simple", "--num-threads", "1"],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    download.assert_called_once_with(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        download_url=url,
    )


@pytest.mark.parametrize(
    ("configured_provider", "recorded_provider", "ignore_missing"),
    [
        (None, "pypi-sdist", False),
        (None, "pypi-sdist", True),
        ("pypi-sdist", "github-tag-git", False),
    ],
)
def test_download_sequence_rejects_missing_or_changed_source_provider(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
    configured_provider: str | None,
    recorded_provider: str,
    ignore_missing: bool,
) -> None:
    """A configured build order must not silently use different settings."""
    if configured_provider is not None:
        _configure_package(tmp_context, f"source:\n  provider: {configured_provider}\n")
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": "https://pkg.test/pkg-1.0.tar.gz",
                    "source_url_type": "override",
                    "source_provider": recorded_provider,
                }
            ]
        )
    )

    with patch.object(download_sequence.sources, "download_source") as download:
        args = [str(build_order), "https://index.test/simple", "--num-threads", "1"]
        if ignore_missing:
            args.append("--ignore-missing-sdists")
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            args,
            obj=tmp_context,
        )

    assert result.exit_code != 0
    assert recorded_provider in str(result.exception)
    download.assert_not_called()


@pytest.mark.parametrize("ignore_missing", [False, True])
def test_download_sequence_rejects_unrecorded_configured_provider(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
    ignore_missing: bool,
) -> None:
    """Old entries cannot use a configured resolver without provenance."""
    _configure_package(
        tmp_context,
        "source:\n"
        "  provider: github-tag-git\n"
        "  project_url: https://github.test/org/pkg\n",
    )
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": "https://pkg.test/pkg-1.0.tar.gz",
                    "source_url_type": "sdist",
                }
            ]
        )
    )
    args = [str(build_order), "https://index.test/simple", "--num-threads", "1"]
    if ignore_missing:
        args.append("--ignore-missing-sdists")

    with patch.object(download_sequence.sources, "download_source") as download:
        result = cli_runner.invoke(
            download_sequence.download_sequence, args, obj=tmp_context
        )

    assert isinstance(result.exception, ValueError)
    assert "github-tag-git" in str(result.exception)
    download.assert_not_called()


def test_download_sequence_checks_providers_before_starting_downloads(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """A later mismatch must fail before an earlier entry downloads."""
    _configure_package(tmp_context, "source:\n  provider: pypi-sdist\n")
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": "https://pkg.test/pkg-1.0.tar.gz",
                    "source_url_type": "override",
                    "source_provider": "pypi-sdist",
                },
                {
                    "dist": "other",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": "https://pkg.test/other-1.0.tar.gz",
                    "source_url_type": "override",
                    "source_provider": "pypi-sdist",
                },
            ]
        )
    )

    with patch.object(download_sequence.sources, "download_source") as download:
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [str(build_order), "https://index.test/simple", "--num-threads", "1"],
            obj=tmp_context,
        )

    assert result.exit_code != 0
    assert "other==1.0" in str(result.exception)
    download.assert_not_called()


def test_download_sequence_skips_test_mode_prebuilt_fallback_source(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """A runtime wheel fallback must not retry its failed source download."""
    _configure_package(tmp_context, "source:\n  provider: pypi-sdist\n")
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": False,
                    "source_url": "https://pkg.test/pkg-1.0.tar.gz",
                    "source_url_type": "prebuilt",
                    "source_provider": "pypi-sdist",
                }
            ]
        )
    )

    with patch.object(download_sequence.sources, "download_source") as download:
        result = cli_runner.invoke(
            download_sequence.download_sequence,
            [str(build_order), "https://index.test/simple", "--num-threads", "1"],
            obj=tmp_context,
        )

    assert result.exit_code == 0, result.output
    download.assert_not_called()


def test_download_sequence_local_mirror_url_skips_download_hook(
    cli_runner: CliRunner, tmp_context: WorkContext, tmp_path: pathlib.Path
) -> None:
    """Download replay fetches a local mirror wheel without invoking its hook."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    tmp_context.wheel_server_url = "https://local.test/simple/"
    url = "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl"
    build_order = tmp_path / "build-order.json"
    build_order.write_text(
        json.dumps(
            [
                {
                    "dist": "pkg",
                    "version": "1.0",
                    "prebuilt": True,
                    "source_url": url,
                    "source_provider": "hook-prebuilt",
                }
            ]
        )
    )
    with (
        patch.object(wheels, "download_wheel") as direct,
        patch("fromager.wheels.sources.download_source") as configured,
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
    direct.assert_called_once_with(
        Requirement("pkg==1.0"), url, tmp_context.wheels_prebuilt
    )
    configured.assert_not_called()


@pytest.mark.parametrize("download_fails", [False, True])
def test_download_sequence_clears_requirement_context(
    cli_runner: CliRunner,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
    download_fails: bool,
) -> None:
    """A prebuilt return or error leaves no package context on the worker."""
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
    failure = ValueError("download failed") if download_fails else None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        with (
            patch.object(
                download_sequence.futures,
                "ThreadPoolExecutor",
                return_value=executor,
            ),
            patch.object(wheels, "download_prebuilt_wheel", side_effect=failure),
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
        assert executor.submit(requirement_ctxvar.get, None).result() is None

    if download_fails:
        assert isinstance(result.exception, ValueError)
    else:
        assert result.exit_code == 0, result.output


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
                    "source_provider": "pypi-sdist",
                }
            ]
        )
    )
    with (
        patch.object(wheels, "download_wheel") as direct,
        patch("fromager.wheels.sources.download_source") as configured,
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
    direct.assert_not_called()


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
        patch("fromager.wheels.sources.download_source") as configured,
        patch.object(build.hooks, "run_prebuilt_wheel_hooks"),
        patch.object(build.server, "update_wheel_mirror") as mirror,
    ):
        result = build._build(tmp_context, version, req, url, False, None)

    assert result.prebuilt is True
    assert result.wheel_filename == tmp_context.wheels_downloads / wheel.name
    legacy.assert_called_once_with(req, url, tmp_context.wheels_build)
    configured.assert_not_called()
    mirror.assert_called_once_with(tmp_context)


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
