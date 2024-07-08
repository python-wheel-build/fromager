from unittest.mock import MagicMock

from unittest.mock import patch
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import sdist


@patch("fromager.sources.resolve_dist")
def test_missing_dependency_format(resolve_dist, tmp_context):
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

@patch("fromager.sources.download_url")
@patch("zipfile.ZipFile")
def test_invalid_wheel_file_exception(mock_zipfile, mock_download_url):
    mock_download_url.return_value = "fake_wheel.csv"
    mock_zip_instance = MagicMock()
    mock_zip_instance.namelist.return_value = ["file1.txt", "file2.txt"]
    mock_zipfile.return_value = mock_zip_instance
    sdist.download_wheel_check(["prebuilt1", "prebuilt2"], "http://example.com/fake_wheel.csv")
    assertRaises(exceptions.TypeError, sdist.download_wheel_check)
