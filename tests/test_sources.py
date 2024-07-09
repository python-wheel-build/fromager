import pathlib

import pytest

from fromager import sources


def test_invalid_tarfile(tmp_path: pathlib.Path):
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    test_url = "https://github.com/python-wheel-build/fromager/blob/main/README.md"
    with pytest.raises(TypeError):
        sources._download_source_check(fake_dir, test_url)
