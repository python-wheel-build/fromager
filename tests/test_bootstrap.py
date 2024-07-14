import pathlib

from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(["a"], [])
    assert [("toplevel", "a")] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(["a", "b"], [])
    assert [("toplevel", "a"), ("toplevel", "b")] == requirements


def test_get_requirements_args_and_file(tmp_path: pathlib.Path):
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("c\n")
    requirements = bootstrap._get_requirements_from_args(
        ["a", "b"], [requirements_file]
    )
    assert [
        ("toplevel", "a"),
        ("toplevel", "b"),
        (str(requirements_file), "c"),
    ] == requirements
