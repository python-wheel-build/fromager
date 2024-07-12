import pathlib
import typing
import zipfile
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import sdist
from fromager.context import WorkContext


@patch("fromager.sources.resolve_dist")
def test_missing_dependency_format(
    resolve_dist: typing.Callable,
    tmp_context: WorkContext,
):
    resolutions = {
        "flit_core": "3.9.0",
        "setuptools": "69.5.1",
    }
    resolve_dist.side_effect = lambda ctx, req, url: (
        "",
        Version(resolutions[req.name]),
    )

    req = Requirement("setuptools>=40.8.0")
    other_reqs = [
        Requirement("flit_core"),
        req,
    ]
    ex = sdist.MissingDependency(tmp_context, "test", req, other_reqs)
    s = str(ex)
    # Ensure we report the thing we're actually missing
    assert "Failed to install test dependency setuptools>=40.8.0. " in s
    # Ensure we report what version we expected of that thing
    assert "setuptools>=40.8.0 -> 69.5.1" in s
    # Ensure we report what version we expect of all of the other dependencies
    assert "flit_core -> 3.9.0" in s


def test_ignore_based_on_marker(tmp_context: WorkContext):
    version = sdist.handle_requirement(
        ctx=tmp_context,
        req=Requirement('foo; python_version<"3.9"'),
        req_type="toplevel",
        why=[],
    )
    assert version == ""


@patch("fromager.sources.download_url")
def test_invalid_wheel_file_exception(mock_download_url, tmp_path: pathlib.Path):
    mock_download_url.return_value = pathlib.Path(tmp_path / "test" / "fake_wheel.txt")
    fake_url = "https://www.thisisafakeurl.com"
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    with pytest.raises(zipfile.BadZipFile):
        sdist._download_wheel_check(fake_dir, fake_url)
