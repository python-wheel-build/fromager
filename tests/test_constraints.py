import pathlib
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints


def test_constraint_is_satisfied_by():
    c = constraints.Constraints({"foo": Requirement("foo<=1.1")})
    assert c.is_satisfied_by("foo", "1.1")
    assert c.is_satisfied_by("foo", Version("1.0"))
    assert c.is_satisfied_by("bar", Version("2.0"))


def test_constraint_canonical_name():
    c = constraints.Constraints({"flash_attn": Requirement("flash_attn<=1.1")})
    assert c.is_satisfied_by("flash_attn", "1.1")
    assert c.is_satisfied_by("flash-attn", "1.1")
    assert c.is_satisfied_by("Flash-ATTN", "1.1")


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
def test_load_constraints_file(parse_requirements_file: Mock, tmp_path: pathlib.Path):
    constraint_file = tmp_path / "constraint.txt"
    constraint_file.write_text("a\n")
    parse_requirements_file.return_value = ["torch==3.1.0"]
    assert constraints.load(constraint_file)._data == {
        "torch": Requirement("torch==3.1.0")
    }
