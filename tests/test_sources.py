import pathlib
import typing
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement

from fromager import context, settings, sources


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


def test_resolve_template_with_no_template():
    req = Requirement("foo==1.0")
    assert sources._resolve_template(None, req, "1.0") is None


def test_resolve_template_with_version():
    req = Requirement("foo==1.0")
    assert sources._resolve_template("url-${version}", req, "1.0") == "url-1.0"


def test_resolve_template_with_no_matching_template():
    req = Requirement("foo==1.0")
    with pytest.raises(KeyError):
        sources._resolve_template("url-${flag}", req, "1.0")


@patch("fromager.sources.resolve_dist")
@patch("fromager.sources._download_source_check")
@patch.object(settings.Settings, "sdist_download_url")
@patch.object(settings.Settings, "sdist_local_filename")
def test_default_download_source_no_predefined_url(
    sdist_local_filename: typing.Callable,
    sdist_download_url: typing.Callable,
    download_source_check: typing.Callable,
    resolve_dist: typing.Callable,
    tmp_context: context.WorkContext,
):
    resolve_dist.return_value = ("url", "1.0")
    download_source_check.return_value = pathlib.Path("filename.zip")
    sdist_download_url.return_value = None
    sdist_local_filename.return_value = None
    req = Requirement("foo==1.0")
    sdist_server_url = sources.PYPI_SERVER_URL

    sources.default_download_source(tmp_context, req, sdist_server_url)

    resolve_dist.assert_called_with(tmp_context, req, sdist_server_url, True, False)
    download_source_check.assert_called_with(tmp_context.sdists_downloads, "url", None)


@patch("fromager.sources.resolve_dist")
@patch("fromager.sources._download_source_check")
@patch.object(settings.Settings, "sdist_download_url")
@patch.object(settings.Settings, "sdist_local_filename")
def test_default_download_source_with_predefined_url(
    sdist_local_filename: typing.Callable,
    sdist_download_url: typing.Callable,
    download_source_check: typing.Callable,
    resolve_dist: typing.Callable,
    tmp_context: context.WorkContext,
):
    resolve_dist.return_value = ("url", "1.0")
    download_source_check.return_value = pathlib.Path("filename")
    sdist_download_url.return_value = "predefined_url-${version}"
    sdist_local_filename.return_value = "foo-${version}"
    req = Requirement("foo==1.0")
    sdist_server_url = sources.PYPI_SERVER_URL

    sources.default_download_source(tmp_context, req, sdist_server_url)

    resolve_dist.assert_called_with(tmp_context, req, sdist_server_url, False, True)
    download_source_check.assert_called_with(
        tmp_context.sdists_downloads, "predefined_url-1.0", "foo-1.0"
    )


@patch("fromager.sources.default_download_source")
def test_invalid_version(mock_default_download):
    ctx = context.WorkContext
    req = Requirement("fake==1.0")
    sdist_server_urls = [sources.PYPI_SERVER_URL]
    mock_default_download.return_value = (
        "fake-1.tar.gz",
        "fake version 1.0",
        "fakesdisturl.com",
    )
    with pytest.raises(ValueError):
        sources.download_source(ctx, req, sdist_server_urls)
