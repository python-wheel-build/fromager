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


def test_compare_req_type():
    assert RequirementType.BUILD == RequirementType.BUILD_BACKEND
    assert RequirementType.BUILD == RequirementType.BUILD_SDIST
    assert RequirementType.BUILD == RequirementType.BUILD_SYSTEM

    # reverse order
    assert RequirementType.BUILD_SYSTEM == RequirementType.BUILD
    assert RequirementType.BUILD_SDIST == RequirementType.BUILD
    assert RequirementType.BUILD_BACKEND == RequirementType.BUILD

    assert RequirementType.INSTALL != RequirementType.BUILD_BACKEND
    assert RequirementType.INSTALL != RequirementType.BUILD_SYSTEM
    assert RequirementType.INSTALL != RequirementType.BUILD_SDIST
    assert RequirementType.INSTALL != RequirementType.BUILD

    # make sure they equal themselves
    for r in RequirementType:
        assert r == r


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
