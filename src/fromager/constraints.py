import copy
import logging
import pathlib
import typing

from packaging.requirements import Requirement

from . import requirements_file

logger = logging.getLogger(__name__)


class Constraints:
    def __init__(self, data: dict[str, Requirement]):
        self._data = data

    def get_constrained_requirement(self, req: Requirement):
        constraint = self._data.get(req.name)
        new_req = copy.deepcopy(req)

        if not constraint:
            return new_req, None

        # only allow one constraint per package
        if len(constraint.specifier) != 1:
            raise ValueError(
                f"{constraint} is not allowed. Only one constraint per package is allowed"
            )

        for spec in constraint.specifier:
            # only allow "=="
            if spec.operator != "==":
                raise ValueError(
                    f"{constraint} is not allowed. Only '<package>==<version>' constraints are allowed"
                )

            # ensure that constraint and req don't conflict
            if spec.version not in req.specifier:
                raise ValueError(
                    f"Constraint {constraint} conflicts with requirement {req}"
                )

        new_req.specifier = constraint.specifier
        return new_req, constraint


def _parse(content: typing.Iterable[str]) -> Constraints:
    constraints = {}
    for line in content:
        req = Requirement(line)
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
