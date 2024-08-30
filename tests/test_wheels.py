import pathlib
import zipfile
from unittest.mock import patch

import pytest

from fromager import wheels


@patch("fromager.sources.download_url")
def test_invalid_wheel_file_exception(mock_download_url, tmp_path: pathlib.Path):
    mock_download_url.return_value = pathlib.Path(tmp_path / "test" / "fake_wheel.txt")
    fake_url = "https://www.thisisafakeurl.com"
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    with pytest.raises(zipfile.BadZipFile):
        wheels._download_wheel_check(fake_dir, fake_url)
