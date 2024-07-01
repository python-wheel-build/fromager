import os
import pathlib
import typing

import pytest
from packaging.requirements import Requirement

from fromager import context, dependencies


@pytest.mark.parametrize(
    "build_system,expected_results",
    [
        # Empty
        ({}, dependencies._DEFAULT_BACKEND),
        # Only specify requirements (pyarrow)
        (
            {"requires": ["a-dep"]},
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
        # Specify everything
        (
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
    ],
)
def test_get_build_backend(
    build_system: dict[str, list[str]] | dict[str, str | list[str] | None],
    expected_results: dict[str, typing.Any] | dict[str, str | list[str] | None],
):
    pyproject_toml = {"build-system": build_system}
    actual = dependencies.get_build_backend(pyproject_toml)
    assert expected_results == actual


def test_get_build_system_dependencies(tmp_context: context.WorkContext):
    fromager_root = pathlib.Path(os.getcwd())
    results = dependencies.get_build_system_dependencies(
        tmp_context,
        Requirement("fromager"),
        fromager_root,
    )
    names = set(r.name for r in results)
    assert names == set(["setuptools", "setuptools_scm"])


def test_get_build_backend_dependencies(tmp_context: context.WorkContext):
    fromager_root = pathlib.Path(os.getcwd())
    results = dependencies.get_build_backend_dependencies(
        tmp_context,
        Requirement("fromager"),
        fromager_root,
    )
    names = set(r.name for r in results)
    assert names == set()


def test_get_build_sdist_dependencies(tmp_context: context.WorkContext):
    fromager_root = pathlib.Path(os.getcwd())
    results = dependencies.get_build_sdist_dependencies(
        tmp_context,
        Requirement("fromager"),
        fromager_root,
    )
    names = set(r.name for r in results)
    assert names == set()


def test_get_install_dependencies(tmp_context: context.WorkContext):
    fromager_root = pathlib.Path(os.getcwd())
    pyproject_contents = dependencies.get_pyproject_contents(fromager_root)
    expected = set(
        Requirement(d) for d in pyproject_contents["project"]["dependencies"]
    )
    actual = dependencies.get_install_dependencies(
        tmp_context,
        Requirement("fromager"),
        fromager_root,
    )
    assert actual == expected
