import logging
import pathlib
from collections.abc import Generator

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import requirements_file

logger = logging.getLogger(__name__)


class Constraints:
    def __init__(self) -> None:
        # mapping of canonical names to requirements
        # NOTE: Requirement.name is not normalized
        self._data: dict[NormalizedName, Requirement] = {}

    def __iter__(self) -> Generator[NormalizedName, None, None]:
        yield from self._data

    def add_constraint(self, unparsed: str) -> None:
        """Add new constraint, must not conflict with any existing constraints"""
        req = Requirement(unparsed)
        canon_name = canonicalize_name(req.name)
        previous = self._data.get(canon_name)
        if previous is not None:
            raise KeyError(
                f"{canon_name}: new constraint '{req}' conflicts with '{previous}'"
            )
        if requirements_file.evaluate_marker(req, req):
            logger.debug(f"adding constraint {req}")
            self._data[canon_name] = req

    def load_constraints_file(self, constraints_file: str | pathlib.Path) -> None:
        """Load constraints from a constraints file"""
        logger.info("loading constraints from %s", constraints_file)
        content = requirements_file.parse_requirements_file(constraints_file)
        for line in content:
            self.add_constraint(line)

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
