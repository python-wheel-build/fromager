import logging
import pathlib

import yaml

from . import overrides

logger = logging.getLogger(__name__)


class Settings:
    def __init__(self, data: dict):
        self._data = data

    def pre_built(self, variant: str) -> set[str]:
        p = self._data.get("pre_built") or {}
        names = p.get(variant) or []
        return set(overrides.pkgname_to_override_module(n) for n in names)


def _parse(content: str) -> Settings:
    data = yaml.safe_load(content)
    return Settings(data)


def load(filename: pathlib.Path) -> Settings:
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        logger.debug("settings file %s does not exist, ignoring", filepath.absolute())
        return Settings({})
    with open(filepath, "r") as f:
        logger.info("loading settings from %s", filepath.absolute())
        return _parse(f)
