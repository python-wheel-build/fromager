import pathlib
import typing
import zipfile
from unittest.mock import Mock, patch

import pytest
from conftest import make_sbom_ctx
from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.version import Version

from fromager import (
    build_environment,
    context,
    downloads,
    packagesettings,
    server,
    wheels,
)
from fromager.packagesettings import SbomSettings, Settings, SettingsFile, WheelSettings


def _configure_package(ctx: context.WorkContext, yaml_str: str) -> None:
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
def test_configured_prebuilt_download_uses_resolver_default(
    tmp_context: context.WorkContext, provider: str
) -> None:
    """Both profiles use their own default when no download hook exists."""
    _configure_package(tmp_context, _source_yaml(provider))
    req = Requirement("pkg==1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    expected = tmp_context.wheels_prebuilt / "pkg-1.0-py3-none-any.whl"
    with (
        patch("fromager.overrides.find_override_method", return_value=None),
        patch("fromager.downloads.download_wheel", return_value=expected) as default,
    ):
        result = wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url=url,
            direct_download_directory=tmp_context.wheels_build,
        )

    assert result == expected
    default.assert_called_once_with(
        destination_dir=tmp_context.wheels_prebuilt, url=url
    )


def test_hook_prebuilt_download_stages_hook_result(
    tmp_context: context.WorkContext,
) -> None:
    """Use the hook's path and make its wheel visible to the local mirror."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")
    url = "https://pkg.test/pkg-1.0-py3-none-any.whl"
    hook_path = tmp_context.work_dir / "pkg-1.0-py3-none-any.whl"
    hook_path.write_bytes(b"wheel")
    calls: list[str] = []

    def hook(download_url: str) -> packagesettings.DownloadedSource:
        calls.append(download_url)
        return packagesettings.DownloadedSource(
            path=hook_path, kind=packagesettings.DownloadKind.prebuilt_wheel
        )

    with (
        patch("fromager.overrides.find_override_method", return_value=hook),
        patch("fromager.downloads.download_wheel") as default,
    ):
        result = wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url=url,
            direct_download_directory=tmp_context.wheels_build,
        )

    assert result == tmp_context.wheels_prebuilt / hook_path.name
    assert result.read_bytes() == b"wheel"
    assert calls == [url]
    default.assert_not_called()


def test_hook_prebuilt_local_url_without_mirror_link_uses_direct_download(
    tmp_context: context.WorkContext,
) -> None:
    """Without a mirror link, a local URL uses the direct downloader, not the hook."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    # No mirror symlink exists, so find_mirror_wheel() returns None.
    tmp_context.wheel_server_url = "https://local.test/simple/"
    req = Requirement("pkg==1.0")
    url = "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl"
    expected = tmp_context.wheels_build / "pkg-1.0-py3-none-any.whl"
    with (
        patch.object(wheels, "download_wheel", return_value=expected) as direct,
        patch("fromager.wheels.sources.download_source") as configured,
    ):
        result = wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url=url,
            direct_download_directory=tmp_context.wheels_build,
        )

    assert result == expected
    direct.assert_called_once_with(req, url, tmp_context.wheels_build)
    configured.assert_not_called()


def test_hook_prebuilt_new_result_replaces_staged_wheel(
    tmp_context: context.WorkContext,
) -> None:
    """A fresh hook result replaces an older staged wheel with the same name."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")
    wheel_name = "pkg-1.0-py3-none-any.whl"
    hook_path = tmp_context.work_dir / wheel_name
    hook_path.write_bytes(b"new wheel")
    staged_path = tmp_context.wheels_prebuilt / wheel_name
    staged_path.write_bytes(b"old wheel")

    with patch(
        "fromager.overrides.find_override_method", return_value=lambda: hook_path
    ):
        result = wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url=f"https://pkg.test/{wheel_name}",
            direct_download_directory=tmp_context.wheels_build,
        )

    assert result == staged_path
    assert staged_path.read_bytes() == b"new wheel"
    assert hook_path.read_bytes() == b"new wheel"
    assert not list(tmp_context.wheels_prebuilt.glob(f".tmp.{wheel_name}.*"))


def test_hook_prebuilt_staging_failure_preserves_existing_wheel(
    tmp_context: context.WorkContext,
) -> None:
    """A failed copy leaves the old staged wheel intact and removes the temp file."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    wheel_name = "pkg-1.0-py3-none-any.whl"
    hook_path = tmp_context.work_dir / wheel_name
    hook_path.write_bytes(b"new wheel")
    staged_path = tmp_context.wheels_prebuilt / wheel_name
    staged_path.write_bytes(b"old wheel")

    with (
        patch(
            "fromager.overrides.find_override_method", return_value=lambda: hook_path
        ),
        patch("fromager.wheels.shutil.copy2", side_effect=OSError("copy failed")),
        pytest.raises(OSError, match="copy failed"),
    ):
        wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=Requirement("pkg==1.0"),
            version=Version("1.0"),
            download_url=f"https://pkg.test/{wheel_name}",
            direct_download_directory=tmp_context.wheels_build,
        )

    assert staged_path.read_bytes() == b"old wheel"
    assert not list(tmp_context.wheels_prebuilt.glob(f".tmp.{wheel_name}.*"))


def test_local_wheel_url_requires_path_boundary() -> None:
    """A different index sharing a URL prefix is not the local mirror."""
    assert wheels.is_local_wheel_url(
        "https://local.test/simple/pkg/pkg-1.0-py3-none-any.whl",
        "https://local.test/simple/",
    )
    assert not wheels.is_local_wheel_url(
        "https://local.test/simple-other/pkg/pkg-1.0-py3-none-any.whl",
        "https://local.test/simple/",
    )


def test_configured_prebuilt_local_url_reuses_mirrored_wheel(
    tmp_context: context.WorkContext,
) -> None:
    """A local mirror URL returns the served file, not a same-named copy."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    wheel_name = "pkg-1.0-py3-none-any.whl"
    served_wheel = tmp_context.wheels_downloads / wheel_name
    served_wheel.write_bytes(b"served wheel")
    server.update_wheel_mirror(tmp_context)
    (tmp_context.wheels_prebuilt / wheel_name).write_bytes(b"other wheel")
    tmp_context.wheel_server_url = "https://local.test/simple/"

    with patch.object(wheels, "download_wheel") as direct:
        result = wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=Requirement("pkg==1.0"),
            version=Version("1.0"),
            download_url=f"https://local.test/simple/pkg/{wheel_name}",
            direct_download_directory=tmp_context.wheels_prebuilt,
        )

    assert result == served_wheel
    direct.assert_not_called()


def test_configured_prebuilt_rejects_other_kind(
    tmp_context: context.WorkContext,
) -> None:
    """An invalid hook result fails without trying a different downloader."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")

    def hook() -> packagesettings.DownloadedSource:
        return packagesettings.DownloadedSource(
            path=tmp_context.work_dir / "pkg-1.0.tar.gz",
            kind=packagesettings.DownloadKind.sdist,
        )

    with (
        patch("fromager.overrides.find_override_method", return_value=hook),
        patch("fromager.downloads.download_wheel") as default,
        pytest.raises(ValueError, match="unsupported kind 'sdist'"),
    ):
        wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url="https://pkg.test/pkg-1.0-py3-none-any.whl",
            direct_download_directory=tmp_context.wheels_build,
        )
    default.assert_not_called()


def test_hook_prebuilt_failure_does_not_fall_back(
    tmp_context: context.WorkContext,
) -> None:
    """Keep the hook failure visible and avoid the default wheel fetch."""
    _configure_package(tmp_context, _source_yaml("hook-prebuilt"))
    req = Requirement("pkg==1.0")
    failure = OSError("hook download failed")

    def hook() -> pathlib.Path:
        raise failure

    with (
        patch("fromager.overrides.find_override_method", return_value=hook),
        patch("fromager.downloads.download_wheel") as default,
        pytest.raises(RuntimeError, match="download_source hook failed") as exc_info,
    ):
        wheels.download_prebuilt_wheel(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url="https://pkg.test/pkg-1.0-py3-none-any.whl",
            direct_download_directory=tmp_context.wheels_build,
        )

    assert exc_info.value.__cause__ is failure
    default.assert_not_called()


@patch("pyproject_hooks.BuildBackendHookCaller.build_wheel")
def test_default_build_wheel(
    mock_build_wheel: Mock,
    tmp_path: pathlib.Path,
    testdata_context: context.WorkContext,
) -> None:
    req = Requirement("test_pkg")
    sdist_root = tmp_path / "test_pkg-1.0"
    sdist_root.mkdir()
    build_env = build_environment.BuildEnvironment(
        ctx=testdata_context,
        req=req,
        sdist_root_dir=sdist_root,
    )
    pbi = testdata_context.package_build_info(req)
    assert pbi.config_settings

    wheels.default_build_wheel(
        ctx=testdata_context,
        build_env=build_env,
        extra_environ={},
        req=req,
        sdist_root_dir=tmp_path,
        version=Version("1.0"),
        build_dir=tmp_path,
    )

    mock_build_wheel.assert_called_once_with(
        str(testdata_context.wheels_build),
        config_settings={
            "setup-args": ["-Dsystem-freetype=true", "-Dsystem-qhull=true"],
            "cmake.define.BLA_VENDOR": "OpenBLAS",
        },
    )


@patch("fromager.external_commands.run")
def test_add_extra_metadata_allows_legitimate_double_dots(
    mock_run: Mock, tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    """Test that add_extra_metadata_to_wheels allows legitimate filenames with '..' in them."""
    req = Requirement("test_pkg==1.0.0")
    version = Version("1.0.0")

    # Create a minimal wheel file with a legitimate file containing ".." in filename
    wheel_dir = tmp_path / "wheel_build"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "test_pkg-1.0.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("test_pkg/__init__.py", "")
        zf.writestr(
            "test_pkg-1.0.0.dist-info/METADATA",
            "Name: test_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "test_pkg-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

        # This should be allowed - ".." is part of filename, not a path component
        zf.writestr("test_pkg/static/js/icon..569adb91.chunk.js", "content")

    # Mock the wheel pack command to avoid actual wheel building
    mock_run.return_value = ""

    # Create a fake rebuilt wheel file to satisfy the function
    (wheel_dir / "test_pkg-1.0.0-0-py3-none-any.whl").touch()

    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()

    # This should NOT raise an error
    result_wheel = wheels.add_extra_metadata_to_wheels(
        ctx=testdata_context,
        req=req,
        version=version,
        extra_environ={},
        sdist_root_dir=sdist_dir,
        wheel_file=wheel_file,
    )

    # Verify the function completed without error
    assert result_wheel.exists()
    mock_run.assert_called_once()


def test_log_existing_sboms_when_present(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that existing SBOM files in .dist-info/sboms/ are logged."""
    req = Requirement("test_pkg==1.0.0")
    dist_info_dir = tmp_path / "test_pkg-1.0.0.dist-info"
    dist_info_dir.mkdir()
    sboms_dir = dist_info_dir / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "cyclonedx.json").write_text("{}")
    (sboms_dir / "other.spdx.json").write_text("{}")

    with caplog.at_level("INFO", logger="fromager.wheels"):
        wheels._log_existing_sboms(req, dist_info_dir)

    assert "found existing SBOM files in wheel" in caplog.text
    assert "cyclonedx.json" in caplog.text
    assert "other.spdx.json" in caplog.text


def test_log_existing_sboms_when_absent(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify no log output when .dist-info/sboms/ does not exist."""
    req = Requirement("test_pkg==1.0.0")
    dist_info_dir = tmp_path / "test_pkg-1.0.0.dist-info"
    dist_info_dir.mkdir()

    with caplog.at_level("INFO", logger="fromager.wheels"):
        wheels._log_existing_sboms(req, dist_info_dir)

    assert "SBOM" not in caplog.text


@patch("fromager.external_commands.run")
def test_add_extra_metadata_generates_sbom_when_enabled(
    mock_run: Mock, tmp_path: pathlib.Path
) -> None:
    """Verify SBOM is generated in .dist-info/sboms/ when sbom settings are configured."""
    sbom_ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    sbom_ctx.setup()
    req = Requirement("test_pkg==1.0.0")
    version = Version("1.0.0")

    wheel_dir = tmp_path / "wheel_build"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "test_pkg-1.0.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_file, "w") as zf:
        zf.writestr("test_pkg/__init__.py", "")
        zf.writestr(
            "test_pkg-1.0.0.dist-info/METADATA",
            "Name: test_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "test_pkg-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

    mock_run.return_value = ""

    # Create the repacked wheel that wheel pack would produce
    repacked = wheel_dir / "test_pkg-1.0.0-0-py3-none-any.whl"

    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()

    # Capture the wheel contents before repack by inspecting what wheel pack receives
    captured_contents: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> str:
        # wheel pack is called with the unpacked dir as second arg
        unpacked_dir = pathlib.Path(cmd[2])
        for f in unpacked_dir.rglob("*"):
            if f.is_file():
                captured_contents.append(str(f.relative_to(unpacked_dir)))
        repacked.touch()
        return ""

    mock_run.side_effect = fake_run

    wheels.add_extra_metadata_to_wheels(
        ctx=sbom_ctx,
        req=req,
        version=version,
        extra_environ={},
        sdist_root_dir=sdist_dir,
        wheel_file=wheel_file,
    )

    # Verify the SBOM file was added to the unpacked wheel before repacking
    assert any("sboms/fromager.spdx.json" in c for c in captured_contents)


def test_download_wheel_unquotes_url_encoded_filenames(tmp_path: pathlib.Path) -> None:
    """Test that download_wheel properly unquotes URL-encoded characters in filenames."""
    req = Requirement("test_pkg")
    # URL with encoded plus sign (%2B)
    wheel_url = "https://example.test/test_pkg-1.0%2Blocal-py3-none-any.whl"

    mock_wheel_file = tmp_path / "mockwheel.whl"
    with zipfile.ZipFile(mock_wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("test_pkg/__init__.py", "")
        zf.writestr(
            "test_pkg-1.0+local.dist-info/METADATA",
            "Name: test_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "test_pkg-1.0+local.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr(
            "test_pkg-1.0+local.dist-info/RECORD",
            "test_pkg/static/js/icon..569adb91.chunk.js,,",
        )

        # This should be allowed - ".." is part of filename, not a path component
        zf.writestr("test_pkg/static/js/icon..569adb91.chunk.js", "content")

    with patch("fromager.request_session.session.get") as mock_get:
        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        with open(mock_wheel_file, "rb") as wf:
            mock_response.iter_content.return_value = [wf.read()]
        mock_get.return_value.__enter__.return_value = mock_response

        result_filename = wheels.download_wheel(req, wheel_url, tmp_path)

        # The filename should be unquoted, containing actual + character
        expected_filename = tmp_path / "test_pkg-1.0+local-py3-none-any.whl"
        assert result_filename == expected_filename


def test_download_url_unquotes_filenames(tmp_path: pathlib.Path) -> None:
    """Test that downloads.download_url properly unquotes URL-encoded characters in filenames."""
    # URL with encoded plus sign (%2B)
    url = "https://example.test/test_pkg-1.0%2Blocal.tar.gz"

    with patch("fromager.request_session.session.get") as mock_get:
        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"test content"]
        mock_get.return_value.__enter__.return_value = mock_response

        result_filename = downloads.download_url(destination_dir=tmp_path, url=url)

        # The filename should be unquoted, containing actual + character
        expected_filename = tmp_path / "test_pkg-1.0+local.tar.gz"
        assert result_filename == expected_filename


def test_add_extra_metadata_blocks_path_traversal(
    tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    """Test that add_extra_metadata_to_wheels blocks actual path traversal attempts."""
    req = Requirement("malicious_pkg==1.0.0")
    version = Version("1.0.0")

    # Create a wheel file with actual path traversal attempt
    wheel_dir = tmp_path / "wheel_build"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "malicious_pkg-1.0.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("malicious_pkg/__init__.py", "")
        zf.writestr(
            "malicious_pkg-1.0.0.dist-info/METADATA",
            "Name: malicious_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "malicious_pkg-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

        # Add a file with actual path traversal (should be blocked)
        zf.writestr("../../../etc/passwd", "malicious content")

    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()

    # This should raise a ValueError due to path traversal attempt
    with pytest.raises(
        ValueError, match="Unsafe path in wheel: \\.\\./\\.\\./\\.\\./etc/passwd"
    ):
        wheels.add_extra_metadata_to_wheels(
            ctx=testdata_context,
            req=req,
            version=version,
            extra_environ={},
            sdist_root_dir=sdist_dir,
            wheel_file=wheel_file,
        )


@pytest.mark.parametrize(
    "dist_name,version_string,wheel_filename,okay",
    [
        ("mypkg", "1.2", "mypkg-1.2-py2.py3-none-any.whl", True),
        ("mypkg", "1.2", "unknown-1.2-py2.py3-none-any.whl", False),
        ("mypkg", "1.2", "mypkg-1.2.1-py2.py3-none-any.whl", False),
        (
            "oslo.messaging",
            "14.7.0",
            "oslo.messaging-14.7.0-py2.py3-none-any.whl",
            True,
        ),
        ("cython", "3.0.10", "Cython-3.0.10-cp311-cp311-linux_aarch64.whl", True),
        (
            "fromage_test",
            "9.9.9",
            "fromage_test-9.9.9-cp311-cp311-linux_aarch64.whl",
            True,
        ),
        # parse_wheel_filename() does NOT accept a dash in the name
        (
            "fromage_test",
            "9.9.9",
            "fromage-test-9.9.9-cp311-cp311-linux_aarch64.whl",
            False,
        ),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6-py3-none-any.whl", True),
    ],
)
def test_validate_wheel_file(
    dist_name: str, version_string: str, wheel_filename: str, okay: bool
) -> None:
    req = Requirement(dist_name)
    version = Version(version_string)
    wheel_file = pathlib.Path(wheel_filename)
    if okay:
        wheels.validate_wheel_filename(req, version, wheel_file)
    else:
        with pytest.raises(ValueError):
            wheels.validate_wheel_filename(req, version, wheel_file)


def _ctx_with_hook(
    tmp_path: pathlib.Path,
    hook: typing.Callable[..., typing.Any] | None = None,
) -> context.WorkContext:
    """Create a WorkContext with an optional build_tag_hook."""
    sf = SettingsFile.from_string("")
    if hook is not None:
        sf = sf.model_copy(update={"wheels": WheelSettings(build_tag_hook=hook)})
    settings = Settings(
        settings=sf,
        package_settings=[],
        variant="cpu",
        patches_dir=tmp_path / "patches",
        max_jobs=None,
    )
    ctx = context.WorkContext(
        active_settings=settings,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        variant="cpu",
    )
    ctx.setup()
    return ctx


class TestGetBuildTag:
    """Tests for ``wheels.get_build_tag()``."""

    def test_no_hook_returns_base_tag(self, tmp_path: pathlib.Path) -> None:
        """Without a hook, get_build_tag returns pbi.build_tag() unchanged."""
        ctx = _ctx_with_hook(tmp_path)
        req = Requirement("mypkg")
        version = Version("1.0")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        result = wheels.get_build_tag(
            ctx=ctx, req=req, version=version, wheel_tags=tags
        )
        pbi = ctx.package_build_info(req)
        assert result == pbi.build_tag(version)

    def test_hook_appends_suffix_segments(
        self, testdata_context: context.WorkContext
    ) -> None:
        """Hook-provided segments are joined and appended to the base tag."""

        def hook(**kwargs: object) -> list[str]:
            return ["el9.6", "rocm7.1"]

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        pbi = testdata_context.package_build_info(req)
        base = pbi.build_tag(version)
        assert base, "test-pkg must have a changelog entry for 1.0.1"
        result = wheels.get_build_tag(
            ctx=testdata_context, req=req, version=version, wheel_tags=tags
        )
        assert len(result) == 2
        assert result[0] == base[0]
        assert result[1] == base[1] + "_el9.6_rocm7.1"

    def test_hook_empty_segments_returns_base(
        self, testdata_context: context.WorkContext
    ) -> None:
        """When hook returns empty list, base tag is returned."""

        def hook(**kwargs: object) -> list[str]:
            return []

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("py3", "none", "any")})
        pbi = testdata_context.package_build_info(req)
        base = pbi.build_tag(version)
        result = wheels.get_build_tag(
            ctx=testdata_context, req=req, version=version, wheel_tags=tags
        )
        assert result == base

    def test_hook_returning_string_raises(
        self, testdata_context: context.WorkContext
    ) -> None:
        """Single string return is rejected (would be iterated as chars)."""

        def hook(**kwargs: object) -> str:
            return "el9.6"

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        with pytest.raises(ValueError, match="sequence of strings"):
            wheels.get_build_tag(
                ctx=testdata_context, req=req, version=version, wheel_tags=tags
            )

    @pytest.mark.parametrize("invalid_segment", ["bad-char", "el9.6\n"])
    def test_hook_invalid_segment_chars_raises(
        self, testdata_context: context.WorkContext, invalid_segment: str
    ) -> None:
        """Segments with invalid characters are rejected."""

        def hook(**kwargs: object) -> list[str]:
            return ["el9.6", invalid_segment]

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        with pytest.raises(ValueError, match="invalid segment"):
            wheels.get_build_tag(
                ctx=testdata_context, req=req, version=version, wheel_tags=tags
            )

    def test_hook_returning_bytes_raises(
        self, testdata_context: context.WorkContext
    ) -> None:
        """Bytes return is rejected the same way as str."""

        def hook(**kwargs: object) -> bytes:
            return b"el9.6"

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        with pytest.raises(ValueError, match="sequence of strings"):
            wheels.get_build_tag(
                ctx=testdata_context, req=req, version=version, wheel_tags=tags
            )

    def test_hook_exception_propagates(
        self, testdata_context: context.WorkContext
    ) -> None:
        """Hook exceptions propagate to the caller."""

        def hook(**kwargs: object) -> list[str]:
            raise RuntimeError("hook failure")

        testdata_context.settings._settings = (
            testdata_context.settings._settings.model_copy(
                update={"wheels": WheelSettings(build_tag_hook=hook)}
            )
        )
        req = Requirement("test-pkg")
        version = Version("1.0.1")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        with pytest.raises(RuntimeError, match="hook failure"):
            wheels.get_build_tag(
                ctx=testdata_context, req=req, version=version, wheel_tags=tags
            )

    def test_hook_not_called_without_base_tag(self, tmp_path: pathlib.Path) -> None:
        """Hook is skipped when the package has no changelog build tag."""
        calls: list[dict[str, object]] = []

        def hook(**kwargs: object) -> list[str]:
            calls.append(kwargs)
            return ["el9.6"]

        ctx = _ctx_with_hook(tmp_path, hook=hook)
        req = Requirement("mypkg")
        version = Version("1.0")
        tags = frozenset({Tag("cp312", "cp312", "linux_x86_64")})
        result = wheels.get_build_tag(
            ctx=ctx, req=req, version=version, wheel_tags=tags
        )
        assert result == ()
        assert calls == []
