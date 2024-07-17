import pathlib
import typing
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints


def test_constraint_is_satisfied_by():
    c = constraints.Constraints({"foo": Requirement("foo<=1.1")})
    assert c.is_satisfied_by("foo", "1.1")
    assert c.is_satisfied_by("foo", Version("1.0"))
    assert c.is_satisfied_by("bar", Version("2.0"))


def test_constraint_not_is_satisfied_by():
    c = constraints.Constraints({"foo": Requirement("foo<=1.1")})
    assert not c.is_satisfied_by("foo", "1.2")
    assert not c.is_satisfied_by("foo", Version("2.0"))


def test_load_empty_constraints_file():
    assert constraints.load(None)._data == {}


def test_load_non_existant_constraints_file(tmp_path: pathlib.Path):
    non_existant_file = tmp_path / "non_existant.txt"
    with pytest.raises(FileNotFoundError):
        constraints.load(non_existant_file)


@patch("fromager.requirements_file.parse_requirements_file")
def test_load_constraints_file(
    parse_requirements_file: typing.Callable, tmp_path: pathlib.Path
):
    constraint_file = tmp_path / "constraint.txt"
    constraint_file.write_text("a\n")
    parse_requirements_file.return_value = ["torch==3.1.0"]
    assert constraints.load(constraint_file)._data == {
        "torch": Requirement("torch==3.1.0")
    }


def test_processing_alternate_repeating_constraints_file():
    input = [
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.9.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.0.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.10.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.10.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.4.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.4.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "requests>1.0",
            "dist": "requests",
            "version": "20.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "requests>1.0", "20.0.0"],
            ],
        },
    ]

    result = constraints._organize_constraints(input)

    assert result[0]["dist"] == input[0]["dist"]
    assert result[1]["dist"] == input[2]["dist"]
    assert result[2]["dist"] == input[1]["dist"]
    assert result[3]["dist"] == input[3]["dist"]
    assert result[4]["dist"] == input[4]["dist"]


def test_processing_repeating_at_the_end_constraints_file():
    input = [
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.9.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "requests>1.0",
            "dist": "requests",
            "version": "20.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "requests>1.0", "20.0.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.0.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.10.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.10.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.4.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.4.0"],
            ],
        },
    ]

    result = constraints._organize_constraints(input)

    assert result[0]["dist"] == input[0]["dist"]
    assert result[1]["dist"] == input[3]["dist"]
    assert result[2]["dist"] == input[2]["dist"]
    assert result[3]["dist"] == input[4]["dist"]
    assert result[4]["dist"] == input[1]["dist"]


def test_processing_duplicates_at_start_constraints_file():
    input = [
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.9.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.10.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.10.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.0.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.4.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.4.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "requests>1.0",
            "dist": "requests",
            "version": "20.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "requests>1.0", "20.0.0"],
            ],
        },
    ]

    result = constraints._organize_constraints(input)

    assert result[0]["dist"] == input[0]["dist"]
    assert result[1]["dist"] == input[1]["dist"]
    assert result[2]["dist"] == input[2]["dist"]
    assert result[3]["dist"] == input[3]["dist"]
    assert result[4]["dist"] == input[4]["dist"]


def test_processing_repeating_groups_constraints_file():
    input = [
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.9.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.10.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.10.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "requests>1.0",
            "dist": "requests",
            "version": "20.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "requests>1.0", "20.0.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.4.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.4.0"],
            ],
        },
        {
            "type": "build_backend",
            "req": "wheel>1.0",
            "dist": "wheel",
            "version": "3.0.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "wheel>1.0", "3.0.0"],
            ],
        },
    ]

    result = constraints._organize_constraints(input)

    assert result[0]["dist"] == input[0]["dist"]
    assert result[1]["dist"] == input[1]["dist"]
    assert result[2]["dist"] == input[3]["dist"]
    assert result[3]["dist"] == input[4]["dist"]
    assert result[4]["dist"] == input[2]["dist"]
