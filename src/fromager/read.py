import io
import pathlib
import typing
from contextlib import contextmanager
from urllib.parse import urlparse

from .request_session import session


@contextmanager
def open_file_or_url(
    path_or_url: str | pathlib.Path,
) -> typing.Generator[io.TextIOBase, typing.Any, None]:
    location = str(path_or_url)
    if location.startswith("file://"):
        location = urlparse(location).path

    if location.startswith(("https://", "http://")):
        response = session.get(location)
        yield io.StringIO(response.text)
    else:
        f = open(location, "r")
        try:
            yield f
        finally:
            f.close()
