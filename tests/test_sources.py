import pathlib
from unittest.mock import Mock, call, patch

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
    with pytest.raises(TypeError):
        sources._download_source_check(fake_dir, fake_url)


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
        include_wheels=False,
    )

    sources.default_download_source(
        testdata_context,
        req,
        Version("42.1.2"),
        "url",
        testdata_context.sdists_downloads,
    )

    download_source_check.assert_called_with(
        testdata_context.sdists_downloads,
        "https://egg.test/test-pkg/v42.1.2.tar.gz",
        "test-pkg-42.1.2.tar.gz",
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
        sources.resolve_source(tmp_context, req, sdist_server_url)


@patch("fromager.sources._apply_patch")
def test_patch_sources_apply_unversioned_and_versioned(
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

    sources.patch_source(
        ctx=tmp_context,
        source_root_dir=source_root_dir,
        req=Requirement("deepspeed==0.5.0"),
        version=Version("0.5.0"),
    )
    assert apply_patch.call_count == 2
    apply_patch.assert_has_calls(
        [
            call(unversioned_patch_file, source_root_dir),
            call(version_patch_file, source_root_dir),
        ]
    )


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

    sources.patch_source(
        ctx=tmp_context,
        source_root_dir=source_root_dir,
        req=Requirement("deepspeed"),
        version=Version("0.6.0"),
    )
    assert apply_patch.call_count == 1
    apply_patch.assert_has_calls(
        [
            call(unversioned_patch_file, source_root_dir),
        ]
    )


@patch("logging.Logger.warning")
def test_warning_for_older_patch(mock, tmp_path: pathlib.Path):
    # create patches dir
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()

    # create patches dir for old version of deepspeed
    deepspeed_old_patch = patches_dir / "deepspeed-0.5.0"
    deepspeed_old_patch.mkdir()
    patch_file = deepspeed_old_patch / "deepspeed-0.5.0.patch"
    patch_file.write_text("This is a test patch")

    # set current source to be a new version of deepspeed
    source_root_dir = tmp_path / "deepspeed-0.6.0"
    source_root_dir.mkdir()

    sources._warn_for_old_patch(
        req=Requirement("deepspeed"),
        version=Version("0.6.0"),
        patches_dir=patches_dir,
    )
    mock.assert_called()


@patch("logging.Logger.warning")
def test_warning_for_older_patch_different_req(mock, tmp_path: pathlib.Path):
    # create patches dir
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()

    # create patches dir for old version of deepspeed
    deepspeed_old_patch = patches_dir / "foo-0.5.0"
    deepspeed_old_patch.mkdir()
    patch_file = deepspeed_old_patch / "foo-0.5.0.patch"
    patch_file.write_text("This is a test patch")

    # set current source to be a new version of deepspeed
    source_root_dir = tmp_path / "deepspeed-0.5.0"
    source_root_dir.mkdir()

    sources._warn_for_old_patch(
        req=Requirement("deepspeed"),
        version=Version("0.5.0"),
        patches_dir=patches_dir,
    )
    mock.assert_not_called()
