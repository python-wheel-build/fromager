import pathlib
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver, sources


@patch("fromager.sources.download_url")
def test_invalid_tarfile(mock_download_url, tmp_path: pathlib.Path):
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
):
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
):
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
def test_invalid_version(mock_default_resolve_source, tmp_context: context.WorkContext):
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
):
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
):
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
