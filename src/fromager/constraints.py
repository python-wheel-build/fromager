import copy
import logging
import pathlib
from io import TextIOWrapper

from packaging.requirements import Requirement

logger = logging.getLogger(__name__)


class Constraints:
    def __init__(self, data: dict[str, Requirement]):
        self._data = data

    def get_new_requirement(self, req: Requirement):
        constraint = self._data.get(req.name)
        new_req = copy.deepcopy(req)

        if not constraint:
            return new_req, None

        # only allow "==" in constraints for now
        if len(constraint.specifier) != 1 or not str(constraint.specifier).startswith(
            "=="
        ):
            logger.debug(
                f"{constraint} is not allowed. Only '<package>==<version>' constraints are allowed"
            )
            return new_req, None

        new_req.specifier = constraint.specifier
        return new_req, constraint


def _parse(content: TextIOWrapper) -> Constraints:
    constraints = {}
    for line in content:
        req = Requirement(line.strip())
        constraints[req.name] = req
    return Constraints(constraints)


def load(filename: pathlib.Path | None) -> Constraints:
    if not filename:
        return Constraints({})
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        logger.debug(
            "constraints file %s does not exist, ignoring", filepath.absolute()
        )
        return Constraints({})
    with open(filepath, "r") as f:
        logger.info("loading constraints from %s", filepath.absolute())
        return _parse(f)
