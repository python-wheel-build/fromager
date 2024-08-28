import pathlib
from importlib import metadata
from unittest import mock
from unittest.mock import patch

import pytest

from fromager import overrides


def test_patches_for_source_dir(tmp_path: pathlib.Path):
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()

    project_patch_dir = patches_dir / "project-1.2.3"
    project_patch_dir.mkdir()

    project_variant_patch_dir = patches_dir / "project-1.2.3-variant"
    project_variant_patch_dir.mkdir()

    p1 = project_patch_dir / "001.patch"
    p2 = project_patch_dir / "002.patch"
    np1 = project_patch_dir / "not-a-patch.txt"
    p3 = project_variant_patch_dir / "003.patch"
    np2 = project_variant_patch_dir / "not-a-patch.txt"

    # Create all of the test files
    for p in [p1, p2, p3]:
        p.write_text("this is a patch file")
    for f in [np1, np2]:
        f.write_text("this is not a patch file")

    results = list(overrides.patches_for_source_dir(patches_dir, "project-1.2.3"))
    assert results == [p1, p2]

    results = list(
        overrides.patches_for_source_dir(patches_dir, "project-1.2.3-variant")
    )
    assert results == [p3]


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


def test_regex_dummy_package(tmp_path: pathlib.Path):
    req_name = "foo"
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()

    lst = [
        patches_dir / "foo-1.1.0",
        patches_dir / "foo-bar-2.0.0",
        patches_dir / "foo-v2.3.0",
        patches_dir / "foo-bar-bar-v2.3.1",
        patches_dir / "foo-bar-v5.5.5",
        patches_dir / "foo-3.4.4",
        patches_dir / "foo-v2.3.0.1",
    ]

    expected = [
        patches_dir / "foo-1.1.0",
        patches_dir / "foo-v2.3.0",
        patches_dir / "foo-3.4.4",
        patches_dir / "foo-v2.3.0.1",
    ]

    actual = overrides._filter_patches_based_on_req(lst, req_name)
    assert len(expected) == len(actual)
    assert expected == actual


def test_regex_for_deepspeed(tmp_path: pathlib.Path):
    req_name = "deepspeed"
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()

    lst = [
        patches_dir / "deepspeed-1.1.0",
        patches_dir / "deepspeed-deep-2.0.0",
        patches_dir / "deepspeed-v2.3.0.post1",
        patches_dir / "deepspeed-v5.5.5",
        patches_dir / "deepspeed-3.4.4",
        patches_dir / "deepspeed-sdg-3.4.4",
    ]

    expected = [
        patches_dir / "deepspeed-1.1.0",
        patches_dir / "deepspeed-v2.3.0.post1",
        patches_dir / "deepspeed-v5.5.5",
        patches_dir / "deepspeed-3.4.4",
    ]

    actual = overrides._filter_patches_based_on_req(lst, req_name)
    assert len(expected) == len(actual)
    assert expected == actual


def test_regex_for_vllm(tmp_path: pathlib.Path):
    req_name = "vllm"
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()

    lst = [
        patches_dir / "vllm-1.1.0.9",
        patches_dir / "vllm-llm-2.1.0.0",
        patches_dir / "vllm-v2.3.5.0.post1",
        patches_dir / "vllm-v5.5.5.1",
    ]

    expected = [
        patches_dir / "vllm-1.1.0.9",
        patches_dir / "vllm-v2.3.5.0.post1",
        patches_dir / "vllm-v5.5.5.1",
    ]

    actual = overrides._filter_patches_based_on_req(lst, req_name)
    assert len(expected) == len(actual)
    assert expected == actual


def test_get_dist_info():
    fromager_version = metadata.version("fromager")
    plugin_dist, plugin_version = overrides._get_dist_info("fromager.submodule")
    assert plugin_dist == "fromager"
    assert plugin_version == fromager_version
