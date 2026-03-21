import pathlib
import sys
import typing
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


@patch("fromager.resolver.resolve")
@patch("fromager.sources._download_source_check")
def test_default_download_source_from_settings(
    download_source_check: Mock,
    resolve: Mock,
    testdata_context: context.WorkContext,
) -> None:
    resolve.return_value = ("url", Version("42.1.2"))
    download_source_check.return_value = pathlib.Path("filename.zip")
    req = Requirement("test_pkg==42.1.2")
    sdist_server_url = "https://sdist.test/egg"

    sources.default_resolve_source(testdata_context, req, sdist_server_url)

    resolve.assert_called_with(
        ctx=testdata_context,
        req=req,
        sdist_server_url=sdist_server_url,
        include_sdists=True,
        include_wheels=True,
        req_type=None,
        ignore_platform=True,
    )

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


@patch("fromager.resolver.resolve")
@patch("fromager.sources._download_source_check")
@patch.multiple(
    packagesettings.PackageBuildInfo,
    resolver_include_sdists=False,
    resolver_include_wheels=True,
    resolver_sdist_server_url=Mock(return_value="url"),
)
def test_default_download_source_with_predefined_resolve_dist(
    download_source_check: Mock,
    resolve: Mock,
    tmp_context: context.WorkContext,
) -> None:
    resolve.return_value = ("url", Version("1.0"))
    download_source_check.return_value = pathlib.Path("filename")
    req = Requirement("foo==1.0")

    sources.default_resolve_source(tmp_context, req, resolver.PYPI_SERVER_URL)

    resolve.assert_called_with(
        ctx=tmp_context,
        req=req,
        sdist_server_url="url",
        include_sdists=False,
        include_wheels=True,
        req_type=None,
        ignore_platform=False,
    )


@patch("fromager.sources.default_resolve_source")
def test_invalid_version(
    mock_default_resolve_source: typing.Any, tmp_context: context.WorkContext
) -> None:
    req = Requirement("fake==1.0")
    sdist_server_url = resolver.PYPI_SERVER_URL
    mock_default_resolve_source.return_value = (
        "fakesdisturl.com",
        "fake version 1.0",
    )
    mock_default_resolve_source.__name__ = "mock_default_resolve_source"
    with pytest.raises(ValueError):
        sources.resolve_source(
            ctx=tmp_context,
            req=req,
            sdist_server_url=sdist_server_url,
        )


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
