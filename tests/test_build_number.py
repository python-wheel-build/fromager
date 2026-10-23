"""Explicit numeric tags must work identically in fresh builds and caches."""

import logging
import pathlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from wheel.wheelfile import WheelFile

from fromager import build_environment, context, packagesettings, server, wheels
from fromager.bootstrapper._cache import (
    _download_wheel_from_cache,
    _look_for_existing_wheel,
)
from fromager.commands.build import _is_wheel_built


def _configure(ctx: context.WorkContext, counter: int) -> None:
    package = packagesettings.PackageSettings.from_mapping(
        "test-pkg",
        {"build_number": {"1.0.1": counter}, "changelog": {"1.0.1": ["a", "b"]}},
        source="test",
        has_config=True,
    )
    ctx.settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(
            changelog={packagesettings.Variant("cpu"): ["global"]}
        ),
        package_settings=[package],
        variant="cpu",
        patches_dir=ctx.settings.patches_dir,
        max_jobs=None,
    )


@pytest.mark.parametrize("counter", [0, 1, 7])
def test_explicit_number_overrides_both_changelogs(
    tmp_context: context.WorkContext, counter: int
) -> None:
    _configure(tmp_context, counter)
    pbi = tmp_context.package_build_info("Test.Pkg")
    assert pbi.build_tag(Version("1.0.1")) == (counter, "")
    assert pbi.build_tag(Version("1.0.1+local")) == (counter, "")
    assert pbi.build_tag(Version("2.0")) == (1, "")
    assert pbi.get_changelog(Version("1.0.1")) == ["global", "a", "b"]
    assert pbi.serialize(mode="json")["build_number"] == {"1.0.1": counter}


@pytest.mark.parametrize("counter", [0, 1, 7])
@pytest.mark.parametrize("cached_tag", ["", "0-", "1-", "2-", "7-"])
def test_local_cache_requires_exact_explicit_number(
    tmp_context: context.WorkContext, counter: int, cached_tag: str
) -> None:
    _configure(tmp_context, counter)
    cached = (
        tmp_context.wheels_downloads / f"test_pkg-1.0.1-{cached_tag}py3-none-any.whl"
    )
    cached.touch()
    with patch(
        "fromager.bootstrapper._cache._extract_build_reqs_from_wheel", return_value=None
    ):
        result, _ = _look_for_existing_wheel(
            tmp_context,
            Requirement("test-pkg"),
            Version("1.0.1"),
            tmp_context.wheels_downloads,
        )
    assert result == (cached if cached_tag == f"{counter}-" else None)


@pytest.mark.parametrize("counter", [0, 1, 7])
@pytest.mark.parametrize("cached_tag", ["", "0-", "1-", "2-", "7-"])
def test_remote_cache_requires_exact_explicit_number(
    tmp_context: context.WorkContext, counter: int, cached_tag: str
) -> None:
    _configure(tmp_context, counter)
    cache_url = "https://cache.test/simple/"
    tmp_context.wheel_server_url = cache_url
    filename = f"test_pkg-1.0.1-{cached_tag}py3-none-any.whl"
    cached = tmp_context.wheels_downloads / filename
    url = cache_url + filename
    with (
        patch(
            "fromager.resolver.find_all_matching_from_provider",
            return_value=[(url, Version("1.0.1"))],
        ),
        patch("fromager.wheels.download_wheel", return_value=cached) as download,
        patch(
            "fromager.bootstrapper._cache._extract_build_reqs_from_wheel",
            return_value=None,
        ),
    ):
        result, _ = _download_wheel_from_cache(
            tmp_context, cache_url, Requirement("test-pkg"), Version("1.0.1")
        )
    assert result == (cached if cached_tag == f"{counter}-" else None)
    assert download.call_count == int(cached_tag == f"{counter}-")


def test_explicit_zero_preserves_suffix_hook(tmp_context: context.WorkContext) -> None:
    _configure(tmp_context, 0)

    def suffix(**kwargs: object) -> list[str]:
        return ["el9", "cuda13"]

    tmp_context.settings._settings = tmp_context.settings._settings.model_copy(
        update={"wheels": packagesettings.WheelSettings(build_tag_hook=suffix)}
    )
    identity = wheels.get_build_tag(
        ctx=tmp_context,
        req=Requirement("test-pkg"),
        version=Version("1.0.1"),
        wheel_tags=frozenset(),
    )
    assert identity == (0, "_el9_cuda13")


@pytest.mark.parametrize("number", [-1, True, "1"])
def test_invalid_explicit_number_is_rejected(number: object) -> None:
    with pytest.raises(RuntimeError, match="failed to load settings"):
        packagesettings.PackageSettings.from_mapping(
            "test-pkg",
            {"build_number": {"1.0": number}},
            source="test",
            has_config=True,
        )


@pytest.mark.parametrize("include_public_key", [False, True])
def test_build_number_rejects_local_version_keys(include_public_key: bool) -> None:
    numbers = {"1.0+vendor": 7}
    if include_public_key:
        numbers["1.0"] = 1
    with pytest.raises(
        RuntimeError, match=r"build_number key '1\.0\+vendor' must be a public version"
    ):
        packagesettings.PackageSettings.from_mapping(
            "test-pkg",
            {"build_number": numbers, "changelog": {"1.0": ["history"]}},
            source="test",
            has_config=True,
        )


def test_public_build_number_applies_to_local_requested_version(
    tmp_context: context.WorkContext,
) -> None:
    _configure(tmp_context, 7)
    pbi = tmp_context.package_build_info("test-pkg")
    assert pbi.build_tag(Version("1.0.1+vendor")) == (7, "")
    assert tmp_context.settings.has_explicit_build_numbers


def test_prebuilt_keeps_original_tag(tmp_context: context.WorkContext) -> None:
    package = packagesettings.PackageSettings.from_mapping(
        "test-pkg",
        {"build_number": {"1.0": 7}, "variants": {"cpu": {"pre_built": True}}},
        source="test",
        has_config=True,
    )
    tmp_context.settings._package_settings[canonicalize_name("test-pkg")] = package
    assert tmp_context.package_build_info("test-pkg").build_tag(Version("1.0")) == ()


@pytest.mark.parametrize("counter", [0, 1, 7])
@pytest.mark.parametrize("cached_tag", ["", "0-", "1-", "2-", "7-"])
@pytest.mark.parametrize("local", [False, True])
def test_build_sequence_cache_requires_exact_explicit_number(
    tmp_context: context.WorkContext, counter: int, cached_tag: str, local: bool
) -> None:
    _configure(tmp_context, counter)
    cache_url = "https://cache.test/simple/"
    tmp_context.wheel_server_url = cache_url if local else ""
    filename = f"test_pkg-1.0.1-{cached_tag}py3-none-any.whl"
    cached = tmp_context.wheels_downloads / filename
    cached.touch()
    with (
        patch(
            "fromager.wheels.resolve_all_cached_wheels",
            return_value=[(cache_url + filename, Version("1.0.1"))],
        ),
        patch("fromager.wheels.download_wheel", return_value=cached) as download,
    ):
        found = _is_wheel_built(
            tmp_context,
            "test-pkg",
            Version("1.0.1"),
            cache_wheel_server_url=None if local else cache_url,
        )
    assert found == (cached if cached_tag == f"{counter}-" else None)
    assert download.call_count == int(not local and cached_tag == f"{counter}-")


def test_legacy_build_sequence_keeps_untagged_zero_and_higher_error(
    tmp_context: context.WorkContext,
) -> None:
    cache_url = "https://cache.test/simple/"
    assert (
        tmp_context.package_build_info("test-pkg").get_build_number(Version("1.0.1"))
        is None
    )
    assert not tmp_context.settings.has_explicit_build_numbers
    with (
        patch(
            "fromager.wheels.resolve_all_cached_wheels",
            return_value=[
                (cache_url + "test_pkg-1.0.1-py3-none-any.whl", Version("1.0.1"))
            ],
        ),
        patch(
            "fromager.wheels.download_wheel",
            return_value=tmp_context.wheels_downloads
            / "test_pkg-1.0.1-py3-none-any.whl",
        ),
    ):
        assert (
            _is_wheel_built(
                tmp_context,
                "test-pkg",
                Version("1.0.1"),
                cache_wheel_server_url=cache_url,
            )
            is not None
        )
    with patch(
        "fromager.wheels.resolve_all_cached_wheels",
        return_value=[
            (cache_url + "test_pkg-1.0.1-1-py3-none-any.whl", Version("1.0.1"))
        ],
    ):
        with pytest.raises(ValueError, match=r"changelog.*inconsistent"):
            _is_wheel_built(
                tmp_context,
                "test-pkg",
                Version("1.0.1"),
                cache_wheel_server_url=cache_url,
            )


def _installation_wheel(
    directory: pathlib.Path,
    name: str,
    version: str,
    build: str,
    requires: str | None = None,
) -> pathlib.Path:
    filename = f"{name}-{version}-{build}-py3-none-any.whl"
    path = directory / filename
    dist = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    if requires:
        metadata += f"Requires-Dist: {requires}\n"
    with WheelFile(path, "w") as archive:
        archive.writestr(f"{name}/__init__.py", f"BUILD = {build!r}\n")
        archive.writestr(f"{dist}/METADATA", metadata)
        archive.writestr(
            f"{dist}/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nBuild: {build}\nTag: py3-none-any\n",
        )
    return path


def test_uv_install_enforces_transitive_counters_in_reused_environment(
    tmp_context: context.WorkContext,
) -> None:
    """Exercise successive installs against the same environment and uv cache.

    Keep this timeline together: fresh environments would miss stale installed
    builds, failed-install recovery, and cache reuse across counter changes.
    """
    # Reproduce the review: a shared index contains builds 0, 1 and 2.
    # uv chooses 2, even though Fromager's desired build is zero.
    _configure(tmp_context, 0)
    for number in ("0", "1", "2"):
        _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", number)
    _installation_wheel(
        tmp_context.wheels_downloads, "consumer", "1.0", "0", "test-pkg==1.0.1"
    )
    server.update_wheel_mirror(tmp_context)
    http_server, sock, thread = server.run_wheel_server(tmp_context)
    source = tmp_context.work_dir / "consumer-src"
    source.mkdir()
    try:
        environment = build_environment.BuildEnvironment(
            ctx=tmp_context,
            req=Requirement("consumer"),
            sdist_root_dir=source,
        )
        environment.run(
            [
                "uv",
                "pip",
                "install",
                "--only-binary",
                ":all:",
                *tmp_context.pip_wheel_server_args,
                "consumer==1.0",
            ],
            network_isolation=False,
        )
        inspect_build = [
            str(environment.python),
            "-c",
            "import test_pkg; print(test_pkg.BUILD)",
        ]
        assert environment.run(inspect_build).strip() == "2"
        # No permitted wheel must fail, even with a newer build already installed
        # and cached by uv. It must not fall back to the broad HTTP index.
        zero = tmp_context.wheels_downloads / "test_pkg-1.0.1-0-py3-none-any.whl"
        zero.unlink()
        with pytest.raises(subprocess.CalledProcessError):
            environment.install([Requirement("consumer==1.0")])
        _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", "0")
        for counter in (0, 1, 7):
            _configure(tmp_context, counter)
            if counter == 7:
                _installation_wheel(
                    tmp_context.wheels_downloads, "test_pkg", "1.0.1", "7"
                )
            environment.install([Requirement("consumer==1.0")])
            assert environment.run(inspect_build).strip() == str(counter)
            installed = environment.run(
                [
                    str(environment.python),
                    "-c",
                    "from importlib.metadata import distribution; print(distribution('test-pkg').read_text('WHEEL'))",
                ]
            )
            assert f"Build: {counter}\n" in installed
        assert len(list(tmp_context.wheels_downloads.glob("test_pkg-*.whl"))) == 4
        assert len(list(tmp_context.work_dir.glob("install-wheels-*"))) == 1
        # A transitive direct file reference bypasses find-links. Validate the
        # installed WHEEL metadata so it cannot be used for compilation either.
        _configure(tmp_context, 0)
        foreign = tmp_context.wheels_downloads / "test_pkg-1.0.1-2-py3-none-any.whl"
        _installation_wheel(
            tmp_context.wheels_downloads,
            "url_consumer",
            "1.0",
            "0",
            f"test-pkg @ {foreign.as_uri()}",
        )
        with pytest.raises(ValueError, match="installed wheel build '2'"):
            environment.install(
                [
                    Requirement("url-consumer==1.0"),
                    Requirement(f"test-pkg @ {foreign.as_uri()}"),
                ]
            )
    finally:
        http_server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_installation_wheelhouse_checks_suffix_and_preserves_legacy_packages(
    tmp_context: context.WorkContext,
) -> None:
    _configure(tmp_context, 0)

    def suffix(**kwargs: object) -> list[str]:
        return ["expected"]

    tmp_context.settings._settings = tmp_context.settings._settings.model_copy(
        update={"wheels": packagesettings.WheelSettings(build_tag_hook=suffix)}
    )
    for build in ("0", "0_expected", "0_other", "2_expected"):
        _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", build)
    _installation_wheel(tmp_context.wheels_downloads, "legacy", "1.0", "2")
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        environment = build_environment.BuildEnvironment(
            ctx=tmp_context,
            req=Requirement("consumer"),
            sdist_root_dir=tmp_context.work_dir,
        )
    with environment._installation_wheel_args(
        tmp_context.settings.has_explicit_build_numbers
    ) as args:
        assert "--no-index" in args and "--offline" in args and "--reinstall" in args
        directory = pathlib.Path(args[args.index("--find-links") + 1])
        assert {path.name for path in directory.glob("*.whl")} == {
            "test_pkg-1.0.1-0_expected-py3-none-any.whl",
            "legacy-1.0-2-py3-none-any.whl",
        }
    assert directory.is_dir()  # Reused by subsequent installs on this worker.


def test_legacy_dependency_installation_keeps_server_arguments(
    tmp_context: context.WorkContext,
) -> None:
    tmp_context.wheel_server_url = "https://legacy.test/simple/"
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        environment = build_environment.BuildEnvironment(
            ctx=tmp_context,
            req=Requirement("consumer"),
            sdist_root_dir=tmp_context.work_dir,
        )
    with environment._installation_wheel_args(
        tmp_context.settings.has_explicit_build_numbers
    ) as args:
        assert args == tmp_context.pip_wheel_server_args


def test_installation_wheel_view_reuses_links_and_refreshes_selection(
    tmp_context: context.WorkContext,
) -> None:
    _configure(tmp_context, 0)
    zero = _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", "0")
    _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", "1")
    legacy = _installation_wheel(tmp_context.wheels_downloads, "legacy", "1.0", "2")
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        environments = [
            build_environment.BuildEnvironment(
                ctx=tmp_context,
                req=Requirement(name),
                sdist_root_dir=tmp_context.work_dir,
            )
            for name in ("consumer", "another-consumer")
        ]
    with (
        patch.object(
            pathlib.Path,
            "symlink_to",
            autospec=True,
            side_effect=pathlib.Path.symlink_to,
        ) as link,
        patch.object(
            build_environment,
            "parse_wheel_filename",
            wraps=build_environment.parse_wheel_filename,
        ) as parse,
    ):
        with environments[0]._installation_wheel_args(True) as first:
            directory = pathlib.Path(first[first.index("--find-links") + 1])
            assert {p.name for p in directory.iterdir()} == {zero.name, legacy.name}
        with environments[1]._installation_wheel_args(True) as second:
            assert first == second
            assert link.call_count == 2
            assert parse.call_count == 3
        # Settings changes must invalidate selection even without new filenames.
        _configure(tmp_context, 1)
        with environments[0]._installation_wheel_args(True):
            assert not (directory / zero.name).exists()
            assert (directory / "test_pkg-1.0.1-1-py3-none-any.whl").exists()
            assert link.call_count == 3
            assert parse.call_count == 3
        legacy.unlink()
        added = _installation_wheel(tmp_context.wheels_prebuilt, "added", "1.0", "0")
        with environments[1]._installation_wheel_args(True):
            assert not (directory / legacy.name).is_symlink()
            assert (directory / added.name).is_file()
            assert link.call_count == 4
            assert parse.call_count == 4


def test_installation_wheel_views_are_isolated_between_workers(
    tmp_context: context.WorkContext,
) -> None:
    _configure(tmp_context, 0)
    wheel = _installation_wheel(tmp_context.wheels_downloads, "test_pkg", "1.0.1", "0")
    barrier = threading.Barrier(2, timeout=10)
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        environment = build_environment.BuildEnvironment(
            ctx=tmp_context,
            req=Requirement("consumer"),
            sdist_root_dir=tmp_context.work_dir,
        )

    def inspect_view() -> pathlib.Path:
        with environment._installation_wheel_args(True) as args:
            directory = pathlib.Path(args[args.index("--find-links") + 1])
            barrier.wait()
            assert (directory / wheel.name).is_file()
            return directory

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(inspect_view) for _ in range(2)]
        directories = [future.result() for future in futures]
    assert directories[0] != directories[1]
    # Thread-local view owners are released when their workers exit.
    assert all(not directory.exists() for directory in directories)


def test_unused_counter_logs_global_installation_policy(
    tmp_context: context.WorkContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(tmp_context, 0)
    _installation_wheel(tmp_context.wheels_downloads, "unrelated", "1.0", "0")
    tmp_context.wheel_server_url = "https://remote.test/simple/"
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        environment = build_environment.BuildEnvironment(
            ctx=tmp_context,
            req=Requirement("unrelated"),
            sdist_root_dir=tmp_context.work_dir,
        )
    with caplog.at_level(logging.INFO):
        with environment._installation_wheel_args(
            tmp_context.settings.has_explicit_build_numbers
        ) as args:
            assert "--offline" in args
            assert "--index-url" not in args
    assert "local-only" in caplog.text
    assert "including unrelated versions" in caplog.text
    assert "--wheel-server-url is not used" in caplog.text
