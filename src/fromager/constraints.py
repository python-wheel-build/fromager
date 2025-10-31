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
        self._data: dict[NormalizedName, list[Requirement]] = {}

    def __iter__(self) -> Generator[NormalizedName, None, None]:
        yield from self._data

    def add_constraint(self, unparsed: str) -> None:
        """Add new constraint, must not conflict with any existing constraints"""
        req = Requirement(unparsed)
        canon_name = canonicalize_name(req.name)
        marker_key = str(req.marker) if req.marker else ""
        previous = self._data.get(canon_name, [])

        # Check for conflicts with existing constraints
        for existing_req in previous:
            existing_marker_key = (
                str(existing_req.marker) if existing_req.marker else ""
            )

            # If markers match (including both being empty), it's a conflict
            if marker_key == existing_marker_key:
                raise KeyError(
                    f"{canon_name}: new constraint '{req}' conflicts with existing constraint '{existing_req}'"
                )

        if canon_name not in self._data:
            self._data[canon_name] = []
        self._data[canon_name].append(req)

    def load_constraints_file(self, constraints_file: str | pathlib.Path) -> None:
        """Load constraints from a constraints file"""
        logger.info("loading constraints from %s", constraints_file)
        content = requirements_file.parse_requirements_file(constraints_file)
        for line in content:
            self.add_constraint(line)

    def get_constraint(self, name: str) -> Requirement | None:
        # Lookup the list by the key given (name), iterate through the list
        # call evaluate_marker(req, req) until it returns true, then return that
        constraints = self._data.get(canonicalize_name(name), [])

        for constraint in constraints:
            if requirements_file.evaluate_marker(constraint, constraint):
                return constraint
        return None

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
