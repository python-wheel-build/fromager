import pathlib
import textwrap

from fromager import requirements_file


def test_get_requirements_requirements_file(tmp_path: pathlib.Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("c\n")
    requirements = requirements_file.parse_requirements_file(req_file)
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
    requirements = requirements_file.parse_requirements_file(req_file)
    assert requirements == ["c", "d"]


def test_get_requirements_file_with_comments_and_blanks(tmp_path: pathlib.Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("a\n\n# ignore\nb\nc\n")
    requirements = requirements_file.parse_requirements_file(req_file)
    assert requirements == ["a", "b", "c"]
