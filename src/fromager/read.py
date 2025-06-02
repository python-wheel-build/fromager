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
        try:
            response = session.get(location)
            response.raise_for_status()
            yield io.StringIO(response.text)
        except Exception as e:
            raise OSError(f"Failed to read from URL {location}: {e}") from e
    else:
        with open(location, "r") as f:
            yield f
