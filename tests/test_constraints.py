import pytest
from packaging.requirements import Requirement

from fromager import constraints


def test_no_constraints():
    c = constraints.Constraints({})
    old_req = Requirement("torch==2.3.0")
    new_req, constraint = c.get_new_requirement(old_req)
    assert new_req == old_req
    assert constraint is None


def test_more_than_one_constraints():
    c = constraints.Constraints({"torch": Requirement("torch==2.3.1,<2.4.0")})
    old_req = Requirement("torch<2.3.0")
    with pytest.raises(ValueError):
        c.get_new_requirement(old_req)


def test_incorrect_operator():
    c = constraints.Constraints({"torch": Requirement("torch!=2.3.1")})
    old_req = Requirement("torch<2.3.0")
    with pytest.raises(ValueError):
        c.get_new_requirement(old_req)


def test_constraint_conflict():
    c = constraints.Constraints({"torch": Requirement("torch==2.3.0")})
    old_req = Requirement("torch!=2.3.0,<2.4.0")
    with pytest.raises(ValueError):
        c.get_new_requirement(old_req)


def test_apply_constraint():
    c = constraints.Constraints({"torch": Requirement("torch==2.3.0")})
    old_req = Requirement("torch!=2.3.1,<2.4.0")
    new_req, constraint = c.get_new_requirement(old_req)
    assert new_req == Requirement("torch==2.3.0")
    assert constraint == Requirement("torch==2.3.0")
