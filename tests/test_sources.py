import pathlib
import sys
import tarfile
import typing
import zipfile
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver, sources


@patch("fromager.sources.download_url")
def test_invalid_tarfile(mock_download_url: typing.Any, tmp_path: pathlib.Path) -> None:
    mock_download_url.return_value = pathlib.Path(tmp_path / "test" / "fake_wheel.txt")
    fake_url = "https://www.thisisafakeurl.com"
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    req = Requirement("test_pkg==42.1.2")
    with pytest.raises(ValueError):
        sources._download_source_check(req=req, destination_dir=fake_dir, url=fake_url)


@patch("fromager.resolver.find_all_matching_from_provider")
@patch("fromager.sources._download_source_check")
def test_resolve_source_from_settings(
    download_source_check: Mock,
    find_all_matching_from_provider: Mock,
    testdata_context: context.WorkContext,
) -> None:
    find_all_matching_from_provider.return_value = [("url", Version("42.1.2"))]
    download_source_check.return_value = pathlib.Path("filename.zip")
    req = Requirement("test_pkg==42.1.2")
    sdist_server_url = "https://sdist.test/egg"

    url, version = sources.resolve_source(
        ctx=testdata_context, req=req, sdist_server_url=sdist_server_url
    )

    # Verify we got the expected result
    assert url == "url"
    assert version == Version("42.1.2")

    sources.default_download_source(
        testdata_context,
        req,
        Version("42.1.2"),
        "url",
        testdata_context.sdists_downloads,
    )

    download_source_check.assert_called_with(
        req=req,
        destination_dir=testdata_context.sdists_downloads,
        url="https://egg.test/test-pkg/v42.1.2.tar.gz",
        destination_filename="test-pkg-42.1.2.tar.gz",
    )


@patch("fromager.resolver.find_all_matching_from_provider")
@patch("fromager.sources._download_source_check")
@patch.multiple(
    packagesettings.PackageBuildInfo,
    resolver_include_sdists=False,
    resolver_include_wheels=True,
    resolver_sdist_server_url=Mock(return_value="url"),
)
def test_resolve_source_with_predefined_resolve_dist(
    download_source_check: Mock,
    find_all_matching_from_provider: Mock,
    tmp_context: context.WorkContext,
) -> None:
    find_all_matching_from_provider.return_value = [("url", Version("1.0"))]
    download_source_check.return_value = pathlib.Path("filename")
    req = Requirement("foo==1.0")

    url, version = sources.resolve_source(
        ctx=tmp_context, req=req, sdist_server_url=resolver.PYPI_SERVER_URL
    )

    # Verify we got the expected result
    assert url == "url"
    assert version == Version("1.0")


@patch("logging.Logger.warning")
@patch("fromager.sources._apply_patch")
def test_patch_sources_apply_unversioned_and_versioned(
    apply_patch: Mock,
    warning: Mock,
    tmp_path: pathlib.Path,
    testdata_context: context.WorkContext,
) -> None:
    source_root_dir = tmp_path / "test_pkg-1.0.2"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-pkg==1.0.2"),
        version=Version("1.0.2"),
    )
    assert apply_patch.call_count == 5
    warning.assert_not_called()

    apply_patch.reset_mock()
    source_root_dir = tmp_path / "test_pkg-1.0.1"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-pkg==1.0.1"),
        version=Version("1.0.1"),
    )
    assert apply_patch.call_count == 2
    warning.assert_not_called()

    apply_patch.reset_mock()
    source_root_dir = tmp_path / "test_other_pkg-1.0.1"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-other-pkg==1.0.1"),
        version=Version("1.0.1"),
    )
    assert apply_patch.call_count == 0
    warning.assert_called_once()


@patch("fromager.sources._apply_patch")
def test_patch_sources_apply_only_unversioned(
    apply_patch: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()
    tmp_context.settings.patches_dir = patches_dir

    deepspeed_version_patch = patches_dir / "deepspeed-0.5.0"
    deepspeed_version_patch.mkdir()
    version_patch_file = deepspeed_version_patch / "deepspeed-0.5.0.patch"
    version_patch_file.write_text("This is a test patch")

    deepspeed_unversioned_patch = patches_dir / "deepspeed"
    deepspeed_unversioned_patch.mkdir()
    unversioned_patch_file = deepspeed_unversioned_patch / "deepspeed-update.patch"
    unversioned_patch_file.write_text("This is a test patch")

    source_root_dir = tmp_path / "deepspeed-0.5.0"
    source_root_dir.mkdir()

    req = Requirement("deepspeed")

    sources.patch_source(
        ctx=tmp_context,
        source_root_dir=source_root_dir,
        req=req,
        version=Version("0.6.0"),
    )
    apply_patch.assert_called_once_with(req, unversioned_patch_file, source_root_dir)


@pytest.mark.parametrize(
    "pkg,version_str,url,expected_filename",
    [
        (
            "mlserver-sklearn==1.6.0",
            "1.6.0",
            "https://github.test/SeldonIO/MLServer/archive/refs/tags/1.6.0.tar.gz",
            "mlserver_sklearn-1.6.0.tar.gz",
        ),
        (
            "some-pkg==2.0",
            "2.0",
            "https://github.test/owner/repo/archive/refs/tags/v2.0.zip",
            "some_pkg-2.0.zip",
        ),
    ],
)
@patch("fromager.sources._download_source_check")
def test_default_download_source_no_destination_filename(
    download_source_check: Mock,
    tmp_context: context.WorkContext,
    pkg: str,
    version_str: str,
    url: str,
    expected_filename: str,
) -> None:
    """When no destination_filename is configured, use PEP 625 normalized name."""
    req = Requirement(pkg)
    version = Version(version_str)

    sources.default_download_source(
        tmp_context, req, version, url, tmp_context.sdists_downloads
    )

    download_source_check.assert_called_with(
        req=req,
        destination_dir=tmp_context.sdists_downloads,
        url=url,
        destination_filename=expected_filename,
    )


@patch("fromager.sources.vendor_rust.vendor_rust")
@patch("fromager.sources.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
def test_prepare_new_source_uses_build_dir_for_vendor_rust(
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    testdata_context: context.WorkContext,
) -> None:
    """Verify vendor_rust is called with build_dir, not source_root_dir.

    This tests the fix for issue #954: packages using build_dir option
    for alternative pyproject.toml location should vendor Rust code
    in the correct directory.
    """
    source_root_dir = tmp_path / "test_pkg-1.0.0"
    source_root_dir.mkdir()
    req = Requirement("test-pkg==1.0.0")
    version = Version("1.0.0")

    sources.prepare_new_source(
        ctx=testdata_context,
        req=req,
        source_root_dir=source_root_dir,
        version=version,
    )

    vendor_rust.assert_called_once_with(req, source_root_dir / "python")


@patch("fromager.sources.vendor_rust.vendor_rust")
@patch("fromager.sources.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
def test_prepare_new_source_uses_source_root_when_no_build_dir(
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify vendor_rust uses source_root_dir when no build_dir is set."""
    source_root_dir = tmp_path / "some_pkg-1.0.0"
    source_root_dir.mkdir()
    req = Requirement("some-pkg==1.0.0")
    version = Version("1.0.0")

    sources.prepare_new_source(
        ctx=tmp_context,
        req=req,
        source_root_dir=source_root_dir,
        version=version,
    )

    vendor_rust.assert_called_once_with(req, source_root_dir)


@pytest.mark.parametrize(
    "dist_name,version_string,sdist_filename,okay",
    [
        ("mypkg", "1.2", "mypkg-1.2.tar.gz", True),
        ("mypkg", "1.2", "unknown-1.2.tar.gz", False),
        ("mypkg", "1.2", "mypkg-1.2.1.tar.gz", False),
        ("oslo.messaging", "14.7.0", "oslo.messaging-14.7.0.tar.gz", True),
        ("cython", "3.0.10", "Cython-3.0.10.tar.gz", True),
        # parse_sdist_filename() accepts a dash in the name
        ("fromage_test", "9.9.9", "fromage-test-9.9.9.tar.gz", True),
        ("fromage-test", "9.9.9", "fromage-test-9.9.9.tar.gz", True),
        ("fromage_test", "9.9.9", "fromage_test-9.9.9.tar.gz", True),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6.tar.gz", True),
    ],
)
def test_validate_sdist_file(
    dist_name: str, version_string: str, sdist_filename: pathlib.Path, okay: bool
) -> None:
    req = Requirement(dist_name)
    version = Version(version_string)
    sdist_file = pathlib.Path(sdist_filename)
    if okay:
        sources.validate_sdist_filename(req, version, sdist_file)
    else:
        with pytest.raises(ValueError):
            sources.validate_sdist_filename(req, version, sdist_file)


# read header of Python executable
with open(sys.executable, "rb") as _f:
    _EXEC_HEADER = _f.read(8)


@pytest.mark.parametrize(
    "filename,content,hit",
    [
        ("test.py", b"#!/usr/bin/python", False),
        ("test.so", b"ignore", True),
        ("test", _EXEC_HEADER, True),
        # assume that packages do not disguise compiled code as .py files.
        # A malicious actor can use more elaborate tricks to hide bad code.
        ("test.py", _EXEC_HEADER, False),
        # ar archive (static library)
        ("libfoo.a", b"!<arch>\n", True),
        # thin ar archive
        ("libfoo.a", b"!<thin>\n", True),
        # Mach-O little-endian
        ("test", b"\xcf\xfa\xed\xfe", True),
        ("test", b"\xce\xfa\xed\xfe", True),
    ],
)
def test_scan_compiled_extensions(
    filename: str, content: bytes, hit: bool, tmp_path: pathlib.Path
) -> None:
    filepath = tmp_path / filename
    with filepath.open("wb") as f:
        f.write(content)
    matches = sources.scan_compiled_extensions(tmp_path)
    if hit:
        assert matches == [pathlib.Path(filename)]
    else:
        assert matches == []


def test_scan_compiled_extensions_broken_symlink(tmp_path: pathlib.Path) -> None:
    """Verify broken symlinks are skipped without raising an error."""
    broken_link = tmp_path / "broken_link"
    broken_link.symlink_to(tmp_path / "nonexistent_target")
    matches = sources.scan_compiled_extensions(tmp_path)
    assert matches == []


def test_write_read_build_meta_roundtrip(tmp_path: pathlib.Path) -> None:
    req = Requirement("numpy==1.0")
    source_filename = tmp_path / "numpy-1.0.tar.gz"

    meta_file = sources.write_build_meta(tmp_path, req, source_filename, Version("1.0"))

    assert meta_file == tmp_path / "build-meta.json"
    assert meta_file.is_file()

    meta = sources.read_build_meta(tmp_path)

    assert meta["req"] == "numpy==1.0"
    assert meta["source-filename"] == str(source_filename)
    assert meta["version"] == "1.0"


def test_ensure_pkg_info_creates_stub_when_missing(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    sdist_root = tmp_path / "pkg-1.0"
    sdist_root.mkdir()

    result = sources.ensure_pkg_info(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        sdist_root_dir=sdist_root,
    )

    assert result is False
    pkg_info = sdist_root / "PKG-INFO"
    assert pkg_info.is_file()
    content = pkg_info.read_text()
    assert "Name: pkg" in content
    assert "Version: 1.0" in content


def test_ensure_pkg_info_returns_true_when_exists(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    sdist_root = tmp_path / "pkg-1.0"
    sdist_root.mkdir()
    (sdist_root / "PKG-INFO").write_text("existing content")

    result = sources.ensure_pkg_info(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        sdist_root_dir=sdist_root,
    )

    assert result is True


def test_ensure_pkg_info_does_not_overwrite_existing(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    sdist_root = tmp_path / "pkg-1.0"
    sdist_root.mkdir()
    pkg_info = sdist_root / "PKG-INFO"
    pkg_info.write_text("existing content")

    sources.ensure_pkg_info(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        sdist_root_dir=sdist_root,
    )

    assert pkg_info.read_text() == "existing content"


def test_ensure_pkg_info_creates_in_both_dirs(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    sdist_root = tmp_path / "pkg-1.0"
    sdist_root.mkdir()
    build_dir = tmp_path / "pkg-1.0" / "python"
    build_dir.mkdir()

    result = sources.ensure_pkg_info(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
        sdist_root_dir=sdist_root,
        build_dir=build_dir,
    )

    assert result is False
    assert (sdist_root / "PKG-INFO").is_file()
    assert (build_dir / "PKG-INFO").is_file()


def test_get_source_type_git(
    tmp_context: context.WorkContext,
) -> None:
    req = Requirement("pkg @ git+https://github.com/org/pkg.git")
    result = sources.get_source_type(tmp_context, req)

    assert result == sources.SourceType.GIT


@patch("fromager.overrides.find_override_method")
def test_get_source_type_override_via_download_source(
    mock_find: Mock,
    tmp_context: context.WorkContext,
) -> None:
    mock_find.side_effect = lambda name, method: (
        (lambda: None) if method == "download_source" else None
    )
    req = Requirement("pkg==1.0")
    result = sources.get_source_type(tmp_context, req)

    assert result == sources.SourceType.OVERRIDE


@patch("fromager.overrides.find_override_method")
def test_get_source_type_override_via_resolver_provider(
    mock_find: Mock,
    tmp_context: context.WorkContext,
) -> None:
    mock_find.side_effect = lambda name, method: (
        (lambda: None) if method == "get_resolver_provider" else None
    )
    req = Requirement("pkg==1.0")
    result = sources.get_source_type(tmp_context, req)

    assert result == sources.SourceType.OVERRIDE


@patch("fromager.overrides.find_override_method", return_value=None)
def test_get_source_type_override_via_download_source_url(
    mock_find: Mock,
    tmp_context: context.WorkContext,
) -> None:
    with patch.object(
        type(tmp_context.package_build_info(Requirement("pkg==1.0"))),
        "download_source_url",
        return_value="https://pkg.test/pkg-1.0.tar.gz",
    ):
        req = Requirement("pkg==1.0")
        result = sources.get_source_type(tmp_context, req)

    assert result == sources.SourceType.OVERRIDE


@patch("fromager.overrides.find_override_method", return_value=None)
def test_get_source_type_sdist(
    mock_find: Mock,
    tmp_context: context.WorkContext,
) -> None:
    req = Requirement("pkg==1.0")
    result = sources.get_source_type(tmp_context, req)

    assert result == sources.SourceType.SDIST


def test_unpack_source_tar_gz(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    req = Requirement("mypkg==1.0")
    version = Version("1.0")
    inner_dir = "mypkg-1.0"

    tar_path = tmp_path / "mypkg-1.0.tar.gz"
    content_dir = tmp_path / "tar_content" / inner_dir
    content_dir.mkdir(parents=True)
    (content_dir / "setup.py").write_text("# setup")
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(content_dir.parent / inner_dir, arcname=inner_dir)

    result, is_new = sources.unpack_source(
        ctx=tmp_context, req=req, version=version, source_filename=tar_path
    )

    assert is_new is True
    assert result.name == inner_dir
    assert (result / "setup.py").is_file()


def test_unpack_source_zip(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    req = Requirement("mypkg==1.0")
    version = Version("1.0")
    inner_dir = "mypkg-1.0"

    zip_path = tmp_path / "mypkg-1.0.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{inner_dir}/setup.py", "# setup")

    result, is_new = sources.unpack_source(
        ctx=tmp_context, req=req, version=version, source_filename=zip_path
    )

    assert is_new is True
    assert result.name == inner_dir
    assert (result / "setup.py").is_file()


def test_unpack_source_unknown_extension(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    req = Requirement("mypkg==1.0")
    version = Version("1.0")
    bad_file = tmp_path / "mypkg-1.0.fake"
    bad_file.write_text("bad")

    with pytest.raises(ValueError):
        sources.unpack_source(
            ctx=tmp_context, req=req, version=version, source_filename=bad_file
        )


def test_unpack_source_renames_mismatched_dir(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    req = Requirement("My-Pkg==1.0")
    version = Version("1.0")
    archive_inner = "My-Pkg-1.0"
    expected_name = "my_pkg-1.0"

    tar_path = tmp_path / "My-Pkg-1.0.tar.gz"
    content_dir = tmp_path / "tar_content" / archive_inner
    content_dir.mkdir(parents=True)
    (content_dir / "setup.py").write_text("# setup")
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(content_dir.parent / archive_inner, arcname=archive_inner)

    result, is_new = sources.unpack_source(
        ctx=tmp_context, req=req, version=version, source_filename=tar_path
    )

    assert is_new is True
    assert result.name == expected_name


def test_unpack_source_reuse_when_no_cleanup(
    tmp_path: pathlib.Path,
) -> None:
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
        cleanup=False,
    )
    ctx.setup()
    req = Requirement("mypkg==1.0")
    version = Version("1.0")

    existing = ctx.work_dir / "mypkg-1.0" / "mypkg-1.0"
    existing.mkdir(parents=True)
    (existing / "setup.py").write_text("# old")

    result, is_new = sources.unpack_source(
        ctx=ctx,
        req=req,
        version=version,
        source_filename=tmp_path / "mypkg-1.0.tar.gz",
    )

    assert is_new is False
    assert result == existing
    assert (result / "setup.py").read_text() == "# old"


@patch("fromager.sources.download_git_source")
def test_download_source_git_already_cloned(
    mock_git: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    clone_dir = tmp_path / "cloned"
    clone_dir.mkdir()
    req = Requirement("pkg @ git+https://github.com/org/pkg.git")

    result = sources.download_source(
        ctx=tmp_context,
        req=req,
        version=Version("1.0"),
        download_url=str(clone_dir),
    )

    assert result == clone_dir
    mock_git.assert_not_called()


@patch("fromager.sources.download_git_source")
def test_download_source_git_with_ref(
    mock_git: Mock,
    tmp_context: context.WorkContext,
) -> None:
    req = Requirement("pkg @ git+https://github.com/org/pkg.git@v2.0")

    result = sources.download_source(
        ctx=tmp_context,
        req=req,
        version=Version("2.0"),
        download_url="/nonexistent",
    )

    mock_git.assert_called_once()
    call_kwargs = mock_git.call_args[1]
    assert call_kwargs["ref"] == "v2.0"
    assert call_kwargs["url_to_clone"] == "https://github.com/org/pkg.git"
    assert result == tmp_context.work_dir / "pkg-2.0" / "pkg-2.0"


@patch("fromager.overrides.find_and_invoke")
def test_download_source_regular_package(
    mock_invoke: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    expected = tmp_path / "pkg-1.0.tar.gz"
    expected.write_text("test")
    mock_invoke.return_value = expected
    req = Requirement("pkg==1.0")

    result = sources.download_source(
        ctx=tmp_context,
        req=req,
        version=Version("1.0"),
        download_url="https://pkg.test/pkg-1.0.tar.gz",
    )

    assert result == expected
    mock_invoke.assert_called_once()


@patch("fromager.overrides.find_and_invoke", return_value="not-a-path")
def test_download_source_invalid_return_raises(
    mock_invoke: Mock,
    tmp_context: context.WorkContext,
) -> None:
    req = Requirement("pkg==1.0")

    with pytest.raises(ValueError):
        sources.download_source(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            download_url="https://pkg.test/pkg-1.0.tar.gz",
        )


@patch("fromager.sources.write_build_meta")
@patch("fromager.overrides.find_and_invoke")
def test_prepare_source_plugin_returns_path(
    mock_invoke: Mock,
    mock_write_meta: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    source_dir = tmp_path / "pkg-1.0"
    source_dir.mkdir()
    mock_invoke.return_value = source_dir
    req = Requirement("pkg==1.0")

    result = sources.prepare_source(
        ctx=tmp_context,
        req=req,
        source_filename=tmp_path / "pkg-1.0.tar.gz",
        version=Version("1.0"),
    )

    assert result == source_dir


@patch("fromager.sources.write_build_meta")
@patch("fromager.overrides.find_and_invoke")
def test_prepare_source_plugin_returns_tuple(
    mock_invoke: Mock,
    mock_write_meta: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    source_dir = tmp_path / "pkg-1.0"
    source_dir.mkdir()
    mock_invoke.return_value = (source_dir, True)
    req = Requirement("pkg==1.0")

    result = sources.prepare_source(
        ctx=tmp_context,
        req=req,
        source_filename=tmp_path / "pkg-1.0.tar.gz",
        version=Version("1.0"),
    )

    assert result == source_dir


@patch("fromager.sources.write_build_meta")
@patch("fromager.overrides.find_and_invoke")
def test_prepare_source_plugin_returns_bad_tuple(
    mock_invoke: Mock,
    mock_write_meta: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    mock_invoke.return_value = (tmp_path, True, "bad")
    req = Requirement("pkg==1.0")

    with pytest.raises(ValueError):
        sources.prepare_source(
            ctx=tmp_context,
            req=req,
            source_filename=tmp_path / "pkg-1.0.tar.gz",
            version=Version("1.0"),
        )


@patch("fromager.overrides.find_and_invoke")
@patch("fromager.packagesettings.get_extra_environ", return_value={})
def test_build_sdist_raises_file_not_found(
    mock_environ: Mock,
    mock_invoke: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    mock_invoke.return_value = tmp_context.sdists_builds / "nonexistent-1.0.tar.gz"

    req = Requirement("pkg==1.0")
    build_env = Mock()

    with pytest.raises(FileNotFoundError):
        sources.build_sdist(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            sdist_root_dir=tmp_path / "src",
            build_env=build_env,
        )


@patch("fromager.overrides.find_and_invoke")
@patch("fromager.packagesettings.get_extra_environ", return_value={})
def test_build_sdist_raises_wrong_directory(
    mock_environ: Mock,
    mock_invoke: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    wrong_dir = tmp_path / "wrong"
    wrong_dir.mkdir()
    sdist_file = wrong_dir / "pkg-1.0.tar.gz"
    sdist_file.write_text("fake sdist")
    mock_invoke.return_value = sdist_file

    req = Requirement("pkg==1.0")
    build_env = Mock()

    with pytest.raises(ValueError):
        sources.build_sdist(
            ctx=tmp_context,
            req=req,
            version=Version("1.0"),
            sdist_root_dir=tmp_path / "src",
            build_env=build_env,
        )
