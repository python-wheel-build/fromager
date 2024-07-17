import collections
import logging
import pathlib
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from . import requirements_file

logger = logging.getLogger(__name__)


class Constraints:
    def __init__(self, data: dict[str, Requirement]):
        self._data = data

    def get_constraint(self, req: Requirement):
        return self._data.get(req.name)

    def is_satisfied_by(self, pkg_name: str, version: Version):
        constraint = self._data.get(pkg_name)
        if constraint:
            return version in constraint.specifier
        return True


def _parse(content: typing.Iterable[str]) -> Constraints:
    constraints = {}
    for line in content:
        req = Requirement(line)
        if requirements_file.evaluate_marker(req, req):
            constraints[req.name] = req
    return Constraints(constraints)


def load(filename: pathlib.Path | None) -> Constraints:
    if not filename:
        return Constraints({})
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        raise FileNotFoundError(
            f"constraints file {filepath.absolute()} does not exist, ignoring"
        )
    logger.info("loading constraints from %s", filepath.absolute())
    parsed_req_file = requirements_file.parse_requirements_file(filename)
    return _parse(parsed_req_file)


# This is a helper function to find and write duplicates to start of the file
# from constraints.txt Input: list of objects (self._build_stack in this case)
# Returns: list of objects (processed_constraints in this case)
def _organize_constraints(info: dict):
    count = collections.Counter([item["dist"] for item in info])
    processed_build_stack = sorted(info, key=lambda item: item["dist"])
    return sorted(
        processed_build_stack, key=lambda item: count[item["dist"]], reverse=True
    )


def write_from_build_order(filename: pathlib.Path, build_stack: list[typing.Any]):
    with open(filename, "w") as f:
        for step in _organize_constraints(build_stack):
            comment = " ".join(
                f"-{dep_type}-> {req.name}({version})"
                for dep_type, req, version in step["why"]
            )
            f.write(f'{step["dist"]}=={step["version"]}  # {comment}\n')
