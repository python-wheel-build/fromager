# mypy: ignore-errors
"""Setup script that intentionally fails during wheel build.

This fixture is designed to pass metadata extraction but fail during
actual wheel building, producing a 'bootstrap' failure in test-mode.
The failure is triggered by a custom build_ext command that always fails.
"""

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class FailingBuildExt(build_ext):
    """Custom build_ext that always fails."""

    def run(self) -> None:
        raise RuntimeError("Intentional build failure for e2e testing")


setup(
    ext_modules=[Extension("test_build_failure._dummy", sources=["missing.c"])],
    cmdclass={"build_ext": FailingBuildExt},
)
