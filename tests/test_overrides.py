import pathlib
from unittest import mock
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import overrides


def test_patches_for_requirement(tmp_path: pathlib.Path):
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()

    project_patch_dir = patches_dir / "project-1.2.3"
    project_patch_dir.mkdir()

    variant_1_patch_dir = project_patch_dir / "brie"
    variant_1_patch_dir.mkdir()

    variant_2_patch_dir = project_patch_dir / "feta"
    variant_2_patch_dir.mkdir()

    gp1 = project_patch_dir / "001.patch"
    gp2 = project_patch_dir / "002.patch"
    sp1 = variant_1_patch_dir / "001.patch"
    sp2 = variant_2_patch_dir / "001.patch"
    np1 = project_patch_dir / "not-a-patch.txt"

    # Create all of the test files
    for gp in [gp1, gp2]:
        gp.write_text("this is a global patch file")
    for sp in [sp1, sp2]:
        sp.write_text("this is a specific patch file")
    for f in [np1]:
        f.write_text("this is not a patch file")

    results_without_variant = list(
        overrides.patches_for_requirement(
            patches_dir=patches_dir,
            req=Requirement("project"),
            version=Version("1.2.3"),
        )
    )

    results_with_variant = list(
        overrides.patches_for_requirement(
            patches_dir=patches_dir,
            req=Requirement("project"),
            version=Version("1.2.3"),
            variant="brie",
        )
    )

    assert results_without_variant == [gp1, gp2]
    assert results_with_variant == [gp1, sp1, gp2]


def test_invoke_override_with_exact_args():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2")


def test_invoke_override_with_more_args_than_needed():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2", arg3="value3")


def test_invoke_override_with_not_enough_args():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    with pytest.raises(TypeError):
        overrides.invoke(foo, arg1="value1")


@patch("fromager.overrides.find_override_method")
def test_find_and_invoke(
    find_override_method: mock.Mock,
):
    def default_foo(arg1):
        return arg1 is not None

    find_override_method.return_value = None

    assert overrides.find_and_invoke(
        "pkg", "foo", default_foo, arg1="value1", arg2="value2"
    )
