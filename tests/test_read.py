import pathlib

import requests_mock

from fromager import read


def test_read_from_file(tmp_path: pathlib.Path):
    file = tmp_path / "test"
    text = ["hello", "world"]
    file.write_text("\n".join(text))
    with read.open_file_or_url(file) as f:
        for index, line in enumerate(f):
            assert line.strip() == text[index]


def test_read_from_url():
    url = "https://someurl.com"
    text = ["hello", "world"]
    with requests_mock.Mocker() as r:
        r.get(url, text="\n".join(text))
        with read.open_file_or_url(url) as f:
            for index, line in enumerate(f):
                assert line.strip() == text[index]
