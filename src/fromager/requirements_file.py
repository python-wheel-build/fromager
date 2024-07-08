import logging
import pathlib
import typing

logger = logging.getLogger(__name__)


def parse_requirements_file(
    req_file: pathlib.Path,
) -> typing.Iterable[str]:
    lines = []
    with open(req_file, "r") as f:
        for line in f:
            useful, _, _ = line.partition("#")
            useful = useful.strip()
            logger.debug("line %r useful %r", line, useful)
            if not useful:
                continue
            lines.append(useful)
    return lines
