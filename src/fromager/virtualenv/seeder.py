"""Virtualenv seeder plugin for Fromager

The plugin installs ``build`` and its dependencies ``packaging`` +
``pyproject_hooks`` into a new virtual environment. The wheel files for
the three packages are bundled and shipped with Fromager. This solves
problems with bootstrapping.

Either Fromager would have to implement a special bootstrapping mode to
build ``build``, ``packaging``, ``pyproject_hooks``, and ``flit-core``
wheels first, then switch its wheel build command to ``build``.

Or Fromager would have to download three pre-built wheels from PyPI.

2. Fromager can create a build environment with the ``build`` command without
   downloading any content from PyPI. Instead it uses the same bundle approach
   as ``virtualenv`` and ``ensurepip``.


"""

import pathlib
import typing

from packaging.utils import parse_wheel_filename

from virtualenv.config.cli.parser import VirtualEnvOptions
from virtualenv.seed.embed.via_app_data.via_app_data import FromAppData
from virtualenv.seed.wheels import Version
from virtualenv.seed.wheels.embed import BUNDLE_SUPPORT

BUNDLED_DIR = pathlib.Path(__file__).parent.resolve() / "bundled"
# `build`` depends on packaging and pyproject_hooks
BUNDLED_PACKAGES = ["build", "packaging", "pyproject_hooks"]


class FromagerSeeder(FromAppData):
    """Custom virtualenv seeder to install build command"""

    def __init__(self, options: VirtualEnvOptions) -> None:
        # register our packages
        for whl, name, version in self.list_extra_packages():
            # add option defaults
            setattr(self, f"no_{name}", False)
            setattr(self, f"{name}_version", version)
            # register wheel files with virtualenv's bundle support
            for py_version in BUNDLE_SUPPORT:
                BUNDLE_SUPPORT[py_version][name] = str(whl)

        # virtualenv no longer installs setuptool and wheels for
        # Python >= 3.12, force installation.
        for opt in ("setuptools", "wheel"):
            if getattr(options, opt) == "none":
                setattr(options, opt, Version.bundle)

        super().__init__(options)

    @classmethod
    def list_extra_packages(cls) -> typing.Iterable[tuple[pathlib.Path, str, str]]:
        for whl in sorted(BUNDLED_DIR.glob("*.whl")):
            name, version, _, _ = parse_wheel_filename(whl.name)
            yield whl, name, str(version)

    @classmethod
    def distributions(cls) -> dict[str, str]:
        dist = super().distributions()
        for _, name, version in cls.list_extra_packages():
            dist[name] = version
        return dist
