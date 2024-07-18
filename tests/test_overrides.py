import os
import pathlib
import typing
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


def test_extra_environ_for_pkg(tmp_path: pathlib.Path):
    env_dir = tmp_path / "env"
    env_dir.mkdir()

    variant_dir = env_dir / "variant"
    variant_dir.mkdir()

    project_env = variant_dir / "project.env"
    project_env.write_text("VAR1=VALUE1\nVAR2=VALUE2")

    result = overrides.extra_environ_for_pkg(env_dir, "project", "variant")
    assert result == {"VAR1": "VALUE1", "VAR2": "VALUE2"}

    result = overrides.extra_environ_for_pkg(env_dir, "non_existant_project", "variant")
    assert result == {}


def test_extra_environ_for_pkg_expansion(tmp_path: pathlib.Path):
    variant = "cpu"
    pkg_name = "another-shrubbery"
    env_file = tmp_path / variant / "another_shrubbery.env"
    env_file.parent.mkdir(parents=True)

    # good case
    with env_file.open("w", encoding="utf=8") as f:
        f.write("EGG = Python\n")
        f.write("SPAM=Monty ${EGG}!\n")
        f.write("KNIGHT=$NAME\n")

    with mock.patch.dict(os.environ) as environ:
        environ.clear()
        environ["NAME"] = "Ni"
        extra_environ = overrides.extra_environ_for_pkg(tmp_path, pkg_name, variant)

    assert extra_environ == {"EGG": "Python", "SPAM": "Monty Python!", "KNIGHT": "Ni"}

    # unknown key
    with env_file.open("w", encoding="utf=8") as f:
        f.write("EGG=${UNKNOWN_NAME}\n")

    with mock.patch.dict(os.environ) as environ:
        environ.clear()
        environ["NAME"] = "Ni"
        with pytest.raises(KeyError):
            extra_environ = overrides.extra_environ_for_pkg(tmp_path, pkg_name, variant)

    # unsupported
    with env_file.open("w", encoding="utf=8") as f:
        f.write("SPAM=$(ls)\n")

    with pytest.raises(ValueError):
        extra_environ = overrides.extra_environ_for_pkg(tmp_path, pkg_name, variant)


def test_list_all(tmp_path: pathlib.Path):
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()

    project_patch_dir = patches_dir / "project-with-patch-1.2.3"
    project_patch_dir.mkdir()

    # legacy form
    p1 = patches_dir / "legacy-project-1.2.3-001.patch"
    np1 = patches_dir / "legacy-project-1.2.3.txt"
    p2 = patches_dir / "fromager_test-1.2.3.patch"  # duplicate

    # new form with project dir
    p3 = project_patch_dir / "003.patch"
    p4 = project_patch_dir / "004.patch"
    np2 = project_patch_dir / "not-a-patch.txt"

    # Create all of the test files
    for p in [p1, p2, p3, p4]:
        p.write_text("this is a patch file")
    for f in [np1, np2]:
        f.write_text("this is not a patch file")

    env_dir = tmp_path / "env"
    env_dir.mkdir()
    variant_dir = env_dir / "variant"
    variant_dir.mkdir()
    project_env = variant_dir / "project-with-env.env"
    project_env.write_text("VAR1=VALUE1\nVAR2=VALUE2")
    project_env2 = variant_dir / "fromager_test.env"
    project_env2.write_text("VAR1=VALUE1\nVAR2=VALUE2")  # duplicate

    download_source = {
        "project-with-download-source": {"url": "url"},
        "another-project-with-download-source": {"url": "url"},
    }

    expected = [
        "project-with-patch",
        "legacy-project",
        "project-with-env",
        "fromager-test",
        "project-with-download-source",
        "another-project-with-download-source",
    ]
    expected.sort()

    packages = overrides.list_all(
        patches_dir=patches_dir,
        envs_dir=env_dir,
        download_source=download_source,
        test=True,
    )

    assert expected == packages


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
    find_override_method: typing.Callable,
):
    def default_foo(arg1):
        return arg1 is not None

    find_override_method.return_value = None

    assert overrides.find_and_invoke(
        "pkg", "foo", default_foo, arg1="value1", arg2="value2"
    )
