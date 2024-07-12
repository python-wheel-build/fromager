import logging
import pathlib
import typing

from packaging import markers
from packaging.requirements import Requirement

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


def evaluate_marker(
    parent_req: Requirement,
    req: Requirement,
    extras: dict | None = None,
) -> bool:
    if not req.marker:
        return True

    default_env = markers.default_environment()
    if not extras:
        marker_envs = [default_env]
    else:
        marker_envs = [default_env.copy() | {"extra": e} for e in extras]

    for marker_env in marker_envs:
        if req.marker.evaluate(marker_env):
            logger.debug(
                f"{parent_req.name}: {req} -- marker evaluates true with extras={extras} and default_env={default_env}"
            )
            return True

    logger.debug(
        f"{parent_req.name}: {req} -- marker evaluates false with extras={extras} and default_env={default_env}"
    )
    return False
