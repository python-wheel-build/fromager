import pathlib
import textwrap
import typing

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from fromager import context, pyproject

PYPROJECT_TOML = """
[build-system]
requires = ["cmake", "setuptools>48.0", "torch>=2.3.0"]
"""

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
    req = Requirement("testproject==1.0.0")
    fixer = pyproject.PyprojectFix(
        req,
        build_dir=tmp_path,
        update_build_requires=["setuptools>=68.0.0"],
        remove_build_requires=[canonicalize_name("cmake")],
    )
    fixer.run()
    with tmp_path.joinpath("pyproject.toml").open(encoding="utf-8") as f:
        doc = tomlkit.load(f)
    assert isinstance(doc["build-system"], typing.Container)
    assert dict(doc["build-system"].items()) == {
        "requires": ["setuptools>=68.0.0"],
    }


def test_pyproject_with_toml(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    tmp_path.joinpath("pyproject.toml").write_text(
        textwrap.dedent("""
            [build-system]
            build-backend = "maturin"
            requires = ["setuptools>=64", "setuptools_scm>=8", "maturin", "cmake>3.0", "torch<2.4.0,>=2.3.1"]
        """)
    )
    req = Requirement("testproject==1.0.0")
    fixer = pyproject.PyprojectFix(
        req,
        build_dir=tmp_path,
        update_build_requires=["setuptools>=68.0.0", "torch"],
        remove_build_requires=[canonicalize_name("cmake")],
    )
    fixer.run()
    with tmp_path.joinpath("pyproject.toml").open(encoding="utf-8") as f:
        doc = tomlkit.load(f)
    assert isinstance(doc["build-system"], typing.Container)
    assert dict(doc["build-system"].items()) == {
        "build-backend": "maturin",
        "requires": [
            "maturin",
            "setuptools>=68.0.0",
            "setuptools_scm>=8",
            "torch",
        ],
    }


def test_pyproject_fix(
    tmp_path: pathlib.Path,
    testdata_context: context.WorkContext,
) -> None:
    pyproject_toml = tmp_path / "python" / "pyproject.toml"
    pyproject_toml.parent.mkdir()
    pyproject_toml.write_text(PYPROJECT_TOML)

    req = Requirement("test-pkg==1.0.0")
    pyproject.apply_project_override(testdata_context, req, tmp_path)

    doc = tomlkit.loads(pyproject_toml.read_text())
    assert isinstance(doc["build-system"], typing.Container)
    assert dict(doc["build-system"].items()) == {
        "requires": [
            "setuptools>=68.0.0",
            "torch",
        ],
    }
