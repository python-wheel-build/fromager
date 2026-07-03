from __future__ import annotations

import io
import pathlib
import tarfile
import typing
import zipfile
from unittest.mock import Mock, patch

import pytest
import requests_mock
from packaging.utils import InvalidSdistFilename, InvalidWheelFilename
from wheel.wheelfile import WheelFile

from fromager.downloads import (
    download_git_source,
    download_sdist,
    download_url,
    download_wheel,
    extract_filename_from_url,
)

# -- extract_filename_from_url ------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://pkg.test/simple/pkg-1.0.tar.gz", "pkg-1.0.tar.gz"),
        ("https://pkg.test/path/to/file.zip", "file.zip"),
        ("https://pkg.test/pkg-1.0%2Blocal.tar.gz", "pkg-1.0+local.tar.gz"),
    ],
)
def test_extract_filename_from_url(url: str, expected: str) -> None:
    assert extract_filename_from_url(url) == expected


# -- download_url -------------------------------------------------------------

_PKG_URL = "https://pkg.test/pkg-1.0.tar.gz"


def test_download_url_creates_file(
    requests_mock: requests_mock.Mocker, tmp_path: pathlib.Path
) -> None:
    requests_mock.get(_PKG_URL, content=b"data")
    result = download_url(destination_dir=tmp_path, url=_PKG_URL)
    assert result == tmp_path / "pkg-1.0.tar.gz"
    assert result.read_bytes() == b"data"


def test_download_url_skips_existing(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pkg-1.0.tar.gz").write_bytes(b"old")
    result = download_url(destination_dir=tmp_path, url=_PKG_URL)
    assert result.read_bytes() == b"old"


def test_download_url_destination_filename(
    requests_mock: requests_mock.Mocker, tmp_path: pathlib.Path
) -> None:
    requests_mock.get(_PKG_URL, content=b"data")
    result = download_url(
        destination_dir=tmp_path, url=_PKG_URL, destination_filename="custom.tar.gz"
    )
    assert result.name == "custom.tar.gz"


def test_download_url_creates_parent_dirs(
    requests_mock: requests_mock.Mocker, tmp_path: pathlib.Path
) -> None:
    requests_mock.get(_PKG_URL, content=b"data")
    assert download_url(destination_dir=tmp_path / "a" / "b", url=_PKG_URL).exists()


def test_download_url_cleans_up_on_failure(
    requests_mock: requests_mock.Mocker, tmp_path: pathlib.Path
) -> None:
    requests_mock.get(_PKG_URL, exc=ConnectionError("fail"))
    with pytest.raises(ConnectionError):
        download_url(destination_dir=tmp_path, url=_PKG_URL)
    assert list(tmp_path.glob(".*")) == []


# -- download_sdist -----------------------------------------------------------

_MOCK_DOWNLOAD_URL = "fromager.downloads.download_url"


def _make_targz(path: pathlib.Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name="dummy.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"test"))


def _make_zip(path: pathlib.Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("dummy.txt", "test")


def _patch_download(filepath: pathlib.Path) -> typing.Any:
    return patch(_MOCK_DOWNLOAD_URL, return_value=filepath)


@pytest.mark.parametrize(
    "filename, maker",
    [
        ("pkg-1.0.tar.gz", _make_targz),
        ("pkg-1.0.zip", _make_zip),
    ],
)
def test_download_sdist_valid(
    tmp_path: pathlib.Path,
    filename: str,
    maker: typing.Callable[[pathlib.Path], None],
) -> None:
    f = tmp_path / filename
    maker(f)
    with _patch_download(f):
        result = download_sdist(
            destination_dir=tmp_path, url=f"https://pkg.test/{filename}"
        )
    assert result == f


def test_download_sdist_rejects_invalid_name(tmp_path: pathlib.Path) -> None:
    with pytest.raises(InvalidSdistFilename):
        download_sdist(
            destination_dir=tmp_path,
            url="https://pkg.test/pkg.exe",
        )


@pytest.mark.parametrize(
    "filename, maker, exc",
    [
        ("pkg-1.0.tar.gz", lambda p: tarfile.open(p, "w:gz").close(), tarfile.TarError),
        ("pkg-1.0.zip", lambda p: zipfile.ZipFile(p, "w").close(), zipfile.BadZipFile),
    ],
)
def test_download_sdist_empty(
    tmp_path: pathlib.Path,
    filename: str,
    maker: typing.Callable[[pathlib.Path], None],
    exc: type[Exception],
) -> None:
    f = tmp_path / filename
    maker(f)
    with _patch_download(f):
        with pytest.raises(exc, match="empty"):
            download_sdist(destination_dir=tmp_path, url=f"https://pkg.test/{filename}")


# -- download_wheel -----------------------------------------------------------

_WHEEL_FILENAME = "pkg-1.0-py3-none-any.whl"
_WHEEL_URL = f"https://pkg.test/{_WHEEL_FILENAME}"


def _make_wheel(path: pathlib.Path, name: str = "pkg", version: str = "1.0") -> None:
    """Create a minimal valid wheel with METADATA, WHEEL, and RECORD."""
    with WheelFile(path, "w") as wf:
        wf.writestr(
            f"{wf.dist_info_path}/METADATA",
            f"Metadata-Version: 1.0\nName: {name}\nVersion: {version}\n",
        )
        wf.writestr(
            f"{wf.dist_info_path}/WHEEL",
            "Wheel-Version: 1.0\n",
        )


def test_download_wheel_valid(tmp_path: pathlib.Path) -> None:
    f = tmp_path / _WHEEL_FILENAME
    _make_wheel(f)
    with _patch_download(f):
        result = download_wheel(
            destination_dir=tmp_path,
            url=_WHEEL_URL,
        )
    assert result == f


def test_download_wheel_rejects_invalid_name(tmp_path: pathlib.Path) -> None:
    with pytest.raises(InvalidWheelFilename):
        download_wheel(
            destination_dir=tmp_path,
            url="https://pkg.test/bad-name.whl",
        )


def test_download_wheel_missing_metadata(tmp_path: pathlib.Path) -> None:
    f = tmp_path / _WHEEL_FILENAME
    with WheelFile(f, "w") as wf:
        wf.writestr(f"{wf.dist_info_path}/WHEEL", "Wheel-Version: 1.0\n")
    with _patch_download(f):
        with pytest.raises(Exception, match="METADATA"):
            download_wheel(
                destination_dir=tmp_path,
                url=_WHEEL_URL,
            )


# -- download_git_source ------------------------------------------------------

_MOCK_GIT_CLONE = "fromager.downloads.gitutils.git_clone_fast"
_GIT_BASE = "git+https://github.test/org/repo.git"


@patch(_MOCK_GIT_CLONE)
def test_git_source_clones(mock_clone: Mock, tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "repo"
    download_git_source(
        destination_dir=dest,
        vcs_url=f"{_GIT_BASE}@refs/tags/v1.0",
    )
    assert dest.is_dir()
    mock_clone.assert_called_once_with(
        output_dir=dest,
        repo_url="https://github.test/org/repo.git",
        ref="refs/tags/v1.0",
    )


def test_git_source_dest_exists(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "repo"
    dest.mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        download_git_source(destination_dir=dest, vcs_url=f"{_GIT_BASE}@v1.0")
