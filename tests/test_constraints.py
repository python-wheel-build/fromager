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

    # Exact duplicate should raise error (same package, same marker)
    with pytest.raises(KeyError):
        c.add_constraint("foo<=1.1")

    # Different version, same marker (no marker) should raise error
    with pytest.raises(KeyError):
        c.add_constraint("foo>1.1")

    # Different version for flit_core should raise error
    with pytest.raises(KeyError):
        c.add_constraint("flit_core>2.0.0")

    # Normalized name conflict should raise error
    with pytest.raises(KeyError):
        c.add_constraint("flit-core>2.0.0")

    # Same package with different markers should NOT raise error
    c.add_constraint("foo==1.0; platform_machine != 'ppc64le'")
    c.add_constraint("foo==1.1; platform_machine == 'ppc64le'")

    # But same package with same marker should raise error
    with pytest.raises(KeyError):
        c.add_constraint("foo==1.2; platform_machine != 'ppc64le'")

    # Verify multiple constraints for same package are stored
    assert len(c._data[constraints.canonicalize_name("foo")]) == 3
    assert len(c._data[constraints.canonicalize_name("flit_core")]) == 1
    assert len(c._data) == 2


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

def test_get_constraint():
    c = constraints.Constraints()

    # Test: No constraint returns None
    assert c.get_constraint("nonexistent") is None

    # Test: Single constraint without marker
    c.add_constraint("foo==1.0")
    constraint = c.get_constraint("foo")
    assert constraint is not None
    assert str(constraint.specifier) == "==1.0"
    assert constraint.marker is None

    # Test: Multiple constraints with markers - should return the one matching current platform
    c.add_constraint("bar==1.0; platform_machine == 'x86_64'")
    c.add_constraint("bar==2.0; platform_machine == 'ppc64le'")
    c.add_constraint("bar==3.0; platform_machine == 'arm64'")

    # get_constraint should return whichever one matches the current platform
    constraint = c.get_constraint("bar")
    assert constraint is not None
    assert str(constraint.specifier) in ["==1.0", "==2.0", "==3.0"]

    # Test: Constraint with marker that evaluates to False returns None
    c.add_constraint("baz==1.0; python_version < '2.0'")
    # This marker should never match (we're not on Python < 2.0)
    constraint = c.get_constraint("baz")
    assert constraint is None

    # Test: Constraint with marker that evaluates to True
    c.add_constraint("qux==1.0; python_version >= '3.0'")
    constraint = c.get_constraint("qux")
    assert constraint is not None
    assert str(constraint.specifier) == "==1.0"

    # Test: Name normalization (foo-bar vs foo_bar)
    c.add_constraint("my-package==1.0")
    constraint = c.get_constraint("my_package")
    assert constraint is not None
    assert str(constraint.specifier) == "==1.0"

    constraint = c.get_constraint("my-package")
    assert constraint is not None
    assert str(constraint.specifier) == "==1.0"
