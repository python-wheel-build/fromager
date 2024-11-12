import logging
import pathlib
import typing

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import requirements_file

logger = logging.getLogger(__name__)


class Constraints:
    def __init__(self, data: dict[str, Requirement]):
        self._data = {canonicalize_name(n): v for n, v in data.items()}

    def get_constraint(self, name: str) -> Requirement | None:
        return self._data.get(canonicalize_name(name))

    def allow_prerelease(self, pkg_name: str) -> bool:
        constraint = self.get_constraint(pkg_name)
        if constraint:
            return bool(constraint.specifier.prereleases)
        return False

    def is_satisfied_by(self, pkg_name: str, version: Version) -> bool:
        constraint = self.get_constraint(pkg_name)
        if constraint:
            return constraint.specifier.contains(version, prereleases=True)
        return True


def _parse(content: typing.Iterable[str]) -> Constraints:
    constraints = {}
    for line in content:
        req = Requirement(line)
        if requirements_file.evaluate_marker(req, req):
            constraints[req.name] = req
    return Constraints(constraints)


def load(constraints_file: str | pathlib.Path | None) -> Constraints:
    if not constraints_file:
        return Constraints({})
    logger.info("loading constraints from %s", constraints_file)
    parsed_req_file = requirements_file.parse_requirements_file(constraints_file)
    return _parse(parsed_req_file)
