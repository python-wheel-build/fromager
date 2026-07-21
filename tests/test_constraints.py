import io
import pathlib
from unittest import mock

import pytest
import requests_mock
from packaging import markers
from packaging.requirements import Requirement
from packaging.version import Version

from fromager.constraints import Constraints, InvalidConstraintError


def test_constraint_is_satisfied_by() -> None:
    c = Constraints()
    assert not c
    c.add_constraint("foo<=1.1")
    assert c
    assert len(c) == 1
    assert c.is_satisfied_by("foo", Version("1.1"))
    assert c.is_satisfied_by("foo", Version("1.0"))
    assert c.is_satisfied_by("bar", Version("2.0"))


def test_constraint_canonical_name() -> None:
    c = Constraints()
    c.add_constraint("flash_attn<=1.1")
    assert c.is_satisfied_by("flash_attn", Version("1.1"))
    assert c.is_satisfied_by("flash-attn", Version("1.1"))
    assert c.is_satisfied_by("Flash-ATTN", Version("1.1"))
    assert list(c) == ["flash-attn"]


def test_constraint_not_is_satisfied_by() -> None:
    c = Constraints()
    c.add_constraint("foo<=1.1")
    c.add_constraint("bar>=2.0")
    assert not c.is_satisfied_by("foo", Version("1.2"))
    assert not c.is_satisfied_by("foo", Version("2.0"))
    assert not c.is_satisfied_by("bar", Version("1.0"))


@mock.patch("platform.machine", mock.Mock(return_value="atari"))
def test_add_constraint_conflict() -> None:
    assert markers.default_environment()["platform_machine"] == "atari"

    c = Constraints()
    c.add_constraint("foo<=1.1")
    c.add_constraint("flit_core==2.0rc3")

    # Conflicting version, same marker (no marker) should raise error
    with pytest.raises(InvalidConstraintError):
        c.add_constraint("foo>1.1")

    # Conflicting version for flit_core should raise error
    with pytest.raises(InvalidConstraintError):
        c.add_constraint("flit_core>2.0.0")

    # Normalized name conflict should raise error
    with pytest.raises(InvalidConstraintError):
        c.add_constraint("flit-core>2.0.0")

    # Constraints for other platforms are ignored
    c.add_constraint(
        "bar==1.0; python_version >= '3.11' and platform_machine == 'amiga'"
    )
    assert c.get_constraint("bar") is None

    c.add_constraint(
        "bar==1.0; python_version >= '3.11' and platform_machine == 'atari'"
    )
    # Make sure correct constraint is added
    constraint = c.get_constraint("bar")
    assert constraint
    assert constraint.name == "bar"
    assert constraint.specifier == "==1.0"
    assert constraint.marker == markers.Marker(
        'python_version >= "3.11" and platform_machine == "atari"'
    )

    # Different, but equivalent markers should raise error
    with pytest.raises(InvalidConstraintError):
        c.add_constraint(
            "bar==1.1; platform_machine == 'atari' and python_version >= '3.11'"
        )

    # Same package with different markers should NOT raise error
    c.add_constraint("baz==1.0; platform_machine != 'amiga'")
    c.add_constraint("baz==1.1; platform_machine == 'amiga'")

    # But same package with same marker should raise error
    with pytest.raises(InvalidConstraintError):
        c.add_constraint("foo==1.2; platform_machine != 'amiga'")

    # Verify multiple constraints for same package are stored
    assert len(c) == 4  # flit_core, foo, bar, and baz


def test_dump_constraints() -> None:
    c = Constraints()

    out = io.StringIO()
    c.dump_constraints(out)
    assert out.getvalue() == ""

    c.add_constraint("foo>=1.0")
    c.add_constraint("foo<2.0")
    c.add_constraint("bar==1.1")

    out = io.StringIO()
    c.dump_constraints(out)
    assert out.getvalue() == "bar==1.1\nfoo<2.0,>=1.0\n"


def test_allow_prerelease() -> None:
    c = Constraints()
    c.add_constraint("foo>=1.1")
    assert not c.allow_prerelease("foo")
    c.add_constraint("bar>=1.1a0")
    assert c.allow_prerelease("bar")
    c.add_constraint("flit_core==2.0rc3")
    assert c.allow_prerelease("flit_core")


def test_load_non_existant_constraints_file(tmp_path: pathlib.Path) -> None:
    non_existant_file = tmp_path / "non_existant.txt"
    c = Constraints()
    with pytest.raises(FileNotFoundError):
        c.load_constraints_file(non_existant_file)


def test_load_constraints_file(tmp_path: pathlib.Path) -> None:
    constraint_file = tmp_path / "constraint.txt"
    constraint_file.write_text("egg==1.0\ntorch==3.1.0 # comment\n")
    c = Constraints()
    c.load_constraints_file(constraint_file)
    assert list(c) == ["egg", "torch"]  # type: ignore
    assert c.get_constraint("torch") == Requirement("torch==3.1.0")


def test_load_constraints_url() -> None:
    c = Constraints()
    url = "https://fromager.test/remote-constraints.txt"
    with requests_mock.Mocker() as r:
        r.get(
            url,
            text="remote>=1.0\n",
        )
        c.load_constraints_file(url)
    assert c.get_constraint("remote") == Requirement("remote>=1.0")


def test_invalid_constraints() -> None:
    c = Constraints()
    with pytest.raises(InvalidConstraintError, match=r".*no specifier"):
        c.add_constraint("foo")
    with pytest.raises(InvalidConstraintError, match=r".*has extras"):
        c.add_constraint("foo[extra]>=1.0")
    with pytest.raises(InvalidConstraintError, match=r".*has a URL"):
        c.add_constraint("foo@https://foo.test")


def test_unsatisfiable() -> None:
    c = Constraints()
    with pytest.raises(InvalidConstraintError):
        c.add_constraint("foo<1.0,>2.0")


def test_combine_constraints() -> None:
    c = Constraints()
    c.add_constraint("foo>=1.0")
    c.add_constraint("foo<2.0")
    assert c.get_constraint("foo") == Requirement("foo<2.0,>=1.0")
    c.add_constraint("foo!=1.1.0")
    assert c.get_constraint("foo") == Requirement("foo<2.0,>=1.0,!=1.1.0")


@pytest.mark.parametrize("specifier", ["<0", "<0.0", "<0.0.0"])
def test_blocked_package(specifier: str) -> None:
    c = Constraints()
    c.add_constraint(f"blocked-pkg{specifier}")
    assert c.is_blocked("blocked-pkg")
    assert not c.is_satisfied_by("blocked-pkg", Version("0"))
    assert not c.is_satisfied_by("blocked-pkg", Version("0.0.1"))
    assert not c.is_satisfied_by("blocked-pkg", Version("1.0"))


def test_blocked_then_non_blocked_raises() -> None:
    c = Constraints()
    c.add_constraint("foo<0")
    with pytest.raises(InvalidConstraintError, match=r"blocked and non-blocked"):
        c.add_constraint("foo>=1.0")


def test_non_blocked_then_blocked_raises() -> None:
    c = Constraints()
    c.add_constraint("foo>=1.0")
    with pytest.raises(InvalidConstraintError, match=r"blocked and non-blocked"):
        c.add_constraint("foo<0")


def test_is_blocked_unknown_package() -> None:
    c = Constraints()
    assert not c.is_blocked("unknown")
