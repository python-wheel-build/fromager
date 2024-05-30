import pathlib

import yaml

from . import overrides


class Settings:

    def __init__(self, data):
        self._data = data

    def pre_built(self, variant):
        p = self._data.get('pre_built') or {}
        names = p.get(variant) or []
        return set(overrides.pkgname_to_override_module(n) for n in names)


def _parse(content):
    data = yaml.safe_load(content)
    return Settings(data)


def load(filename):
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        return Settings({})
    with open(filename, 'r') as f:
        return _parse(f)
