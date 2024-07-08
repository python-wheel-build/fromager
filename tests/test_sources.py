import pathlib
import tarfile

import pytest

from fromager import sources


def test_invalid_tarfile(tmp_path: pathlib.Path):
    # fake_file_path = "/home/rdevasth/fromager/tests/fake_wheel.txt"
    # with pytest.raises(tarfile.ReadError):
    #     with tarfile.open(fake_file_path) as tar:
    #         tar.getnames()

    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    with pytest.raises(tarfile.ReadError):
        sources._download_source_check(fake_dir, text_file)
