import pathlib

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints


def test_constraint_is_satisfied_by():
    c = constraints.Constraints()
    c.add_constraint("foo<=1.1")
    assert c.is_satisfied_by("foo", "1.1")
    assert c.is_satisfied_by("foo", Version("1.0"))
    assert c.is_satisfied_by("bar", Version("2.0"))


def test_constraint_canonical_name():
    c = constraints.Constraints()
    c.add_constraint("flash_attn<=1.1")
    assert c.is_satisfied_by("flash_attn", "1.1")
    assert c.is_satisfied_by("flash-attn", "1.1")
    assert c.is_satisfied_by("Flash-ATTN", "1.1")
    assert list(c) == ["flash-attn"]


def test_constraint_not_is_satisfied_by():
    c = constraints.Constraints()
    c.add_constraint("foo<=1.1")
    c.add_constraint("bar>=2.0")
    assert not c.is_satisfied_by("foo", "1.2")
    assert not c.is_satisfied_by("foo", Version("2.0"))
    assert not c.is_satisfied_by("bar", Version("1.0"))


def test_add_constraint_conflict():
    c = constraints.Constraints()
    c.add_constraint("foo<=1.1")
    c.add_constraint("flit_core==2.0rc3")
    with pytest.raises(KeyError):
        c.add_constraint("foo<=1.1")
    with pytest.raises(KeyError):
        c.add_constraint("foo>1.1")
    with pytest.raises(KeyError):
        c.add_constraint("flit_core>2.0.0")
    with pytest.raises(KeyError):
        c.add_constraint("flit-core>2.0.0")


def test_allow_prerelease():
    c = constraints.Constraints()
    c.add_constraint("foo>=1.1")
    assert not c.allow_prerelease("foo")
    c.add_constraint("bar>=1.1a0")
    assert c.allow_prerelease("bar")
    c.add_constraint("flit_core==2.0rc3")
    assert c.allow_prerelease("flit_core")


def test_load_non_existant_constraints_file(tmp_path: pathlib.Path):
    non_existant_file = tmp_path / "non_existant.txt"
    c = constraints.Constraints()
    with pytest.raises(FileNotFoundError):
        c.load_constraints_file(non_existant_file)


def test_load_constraints_file(tmp_path: pathlib.Path):
    constraint_file = tmp_path / "constraint.txt"
    constraint_file.write_text("egg\ntorch==3.1.0 # comment\n")
    c = constraints.Constraints()
    c.load_constraints_file(constraint_file)
    assert list(c) == ["egg", "torch"]  # type: ignore
    assert c.get_constraint("torch") == Requirement("torch==3.1.0")
