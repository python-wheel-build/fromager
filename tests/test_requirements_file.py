import pathlib
import textwrap
from itertools import product

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement

from fromager.requirements_file import (
    RequirementType,
    evaluate_marker,
    parse_requirements_file,
)


def test_get_requirements_requirements_file(tmp_path: pathlib.Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("c\n")
    requirements = parse_requirements_file(req_file)
    assert requirements == ["c"]


def test_get_requirements_requirements_file_comments(tmp_path: pathlib.Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        textwrap.dedent("""
        c
        d # with comment
        # ignore comment

        """),
    )
    requirements = parse_requirements_file(req_file)
    assert requirements == ["c", "d"]


def test_get_requirements_file_with_comments_and_blanks(tmp_path: pathlib.Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("a\n\n# ignore\nb\nc\n")
    requirements = parse_requirements_file(req_file)
    assert requirements == ["a", "b", "c"]


def test_req_type_flag():
    assert not RequirementType.INSTALL.is_build_requirement
    assert not RequirementType.TOP_LEVEL.is_build_requirement
    assert RequirementType.BUILD_SYSTEM.is_build_requirement
    assert RequirementType.BUILD_SDIST.is_build_requirement
    assert RequirementType.BUILD_BACKEND.is_build_requirement

    assert RequirementType.INSTALL.is_install_requirement
    assert RequirementType.TOP_LEVEL.is_install_requirement
    assert not RequirementType.BUILD_SYSTEM.is_install_requirement
    assert not RequirementType.BUILD_SDIST.is_install_requirement
    assert not RequirementType.BUILD_BACKEND.is_install_requirement

    for r in RequirementType:
        assert r == r
        assert r.is_build_requirement or r.is_install_requirement


@pytest.mark.parametrize(
    "parent_e,marker_e,extras_e", list(product(["b-c", "b_c", "B_C"], repeat=3))
)
def test_evaluate_marker_canonical_names(parent_e, marker_e, extras_e):
    parent_req = Requirement(f"a[{parent_e}]")
    req = Requirement("d")
    marker = Marker(f"extra == '{marker_e}'")
    req.marker = marker
    extras = set([extras_e])
    assert evaluate_marker(parent_req=parent_req, req=req, extras=extras)
