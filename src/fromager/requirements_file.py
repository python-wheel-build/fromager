import logging
import pathlib
import typing
from enum import StrEnum

from packaging import markers
from packaging.requirements import Requirement

from .read import open_file_or_url

logger = logging.getLogger(__name__)


class RequirementType(StrEnum):
    INSTALL = "install"
    TOP_LEVEL = "toplevel"
    BUILD_SYSTEM = "build-system"
    BUILD_BACKEND = "build-backend"
    BUILD_SDIST = "build-sdist"

    @property
    def is_build_requirement(self) -> bool:
        """Is requirement a build time requirement?"""
        return self.value in {"build-system", "build-backend", "build-sdist"}

    @property
    def is_install_requirement(self) -> bool:
        """Is requirement an installation requirement?"""
        return self.value in {"install", "toplevel"}


class SourceType(StrEnum):
    PREBUILT = "prebuilt"
    SDIST = "sdist"
    OVERRIDE = "override"
    GIT = "git"


def parse_requirements_file(
    req_file: str | pathlib.Path,
) -> typing.Iterable[str]:
    logger.debug("reading requirements file %s", req_file)
    lines = []
    with open_file_or_url(req_file) as f:
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
    extras: set[str] | None = None,
) -> bool:
    if not req.marker:
        return True

    # fixes mypy complaining about types: https://github.com/pypa/packaging/blob/main/src/packaging/markers.py#L310
    default_env = typing.cast(dict[str, str], markers.default_environment())
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
