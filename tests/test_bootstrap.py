import typing
from unittest.mock import patch

from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(["a"], [])
    assert [("toplevel", "a")] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(["a", "b"], [])
    assert [("toplevel", "a"), ("toplevel", "b")] == requirements


@patch("fromager.requirements_file.parse_requirements_file")
def test_get_requirements_args_and_file(parse_requirements_file: typing.Callable):
    requirements_file = "requirements.txt"
    parse_requirements_file.return_value = ["c"]
    requirements = bootstrap._get_requirements_from_args(
        ["a", "b"], [requirements_file]
    )
    assert [
        ("toplevel", "a"),
        ("toplevel", "b"),
        (str(requirements_file), "c"),
    ] == requirements
