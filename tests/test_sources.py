import pathlib
from unittest.mock import patch

import pytest

from fromager import sources


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
