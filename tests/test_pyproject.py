import pathlib
import textwrap
import typing

import tomlkit
from packaging.requirements import Requirement

from fromager import context, pyproject, settings

TEST_SETTINGS = {
    "pyproject_overrides": {
        "auto_build_requires": {
            "ninja": "ninja",
            "packaging": "packaging",
            "pybind11": "pybind11",
            "setuptools": "setuptools",
            "torch": "torch<2.4.0,>=2.3.1",
            "wheels": "wheels",
        },
        "remove_build_requires": [
            "cmake",
        ],
        "replace_build_requires": {"setuptools": "setuptools>=68.0.0"},
    }
}


def test_pyproject_no_toml(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    tmp_context.settings = settings.Settings(TEST_SETTINGS)
    req = Requirement("testproject==0.0.1")
    tmp_path.joinpath("setup.py").write_text(
        textwrap.dedent("""
            import torch
            import distutils
        """)
    )
    fixer = pyproject.PyprojectFixer(tmp_context, req, tmp_path)
    fixer.update()
    with tmp_path.joinpath("pyproject.toml").open(encoding="utf-8") as f:
        doc = tomlkit.load(f)
    assert isinstance(doc["build-system"], typing.Container)
    assert dict(doc["build-system"].items()) == {
        "requires": ["setuptools>=68.0.0", "torch<2.4.0,>=2.3.1"],
    }


def test_pyproject_with_toml(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    tmp_context.settings = settings.Settings(TEST_SETTINGS)
    req = Requirement("testproject==0.0.1")
    tmp_path.joinpath("setup.py").write_text(
        textwrap.dedent("""
            import pybind11, ninja
            import wheels
            from packaging import version

            def func():
                from torch import cuda

        """)
    )
    tmp_path.joinpath("pyproject.toml").write_text(
        textwrap.dedent("""
            [build-system]
            build-backend = "maturin"
            requires = ["setuptools>=64", "setuptools_scm>=8", "maturin", "cmake>3.0"]
        """)
    )
    fixer = pyproject.PyprojectFixer(tmp_context, req, tmp_path)
    fixer.update()
    with tmp_path.joinpath("pyproject.toml").open(encoding="utf-8") as f:
        doc = tomlkit.load(f)
    assert isinstance(doc["build-system"], typing.Container)
    assert dict(doc["build-system"].items()) == {
        "build-backend": "maturin",
        "requires": [
            "maturin",
            "ninja",
            "packaging",
            "pybind11",
            "setuptools>=68.0.0",
            "setuptools_scm>=8",
            "torch<2.4.0,>=2.3.1",
            "wheels",
        ],
    }
