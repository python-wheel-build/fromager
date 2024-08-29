import io
import pathlib
import textwrap

from packaging.requirements import Requirement
from packaging.version import Version

from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(["a"], [])
    assert ["a"] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(["a", "b"], [])
    assert ["a", "b"] == requirements


def test_get_requirements_args_and_file(tmp_path: pathlib.Path):
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("c\n")
    requirements = bootstrap._get_requirements_from_args(
        ["a", "b"], [requirements_file]
    )
    assert [
        "a",
        "b",
        "c",
    ] == requirements


def test_reverse_dependency_graph():
    graph = {
        "a==1.0": [
            ("install", "b", Version("2.0"), Requirement("b>=2.0")),
            ("install", "c", Version("3.0"), Requirement("c<4.0")),
        ],
    }
    reverse_graph = bootstrap.reverse_dependency_graph(graph)
    assert {
        "b==2.0": [("a==1.0", Requirement("b>=2.0"))],
        "c==3.0": [("a==1.0", Requirement("c<4.0"))],
    } == reverse_graph


def test_write_constraints_file_simple():
    buffer = io.StringIO()
    graph = {
        "": [("install", "a", Version("1.0"), Requirement("a"))],
        "a==1.0": [
            ("install", "b", Version("2.0"), Requirement("b>=2.0")),
            ("install", "c", Version("3.0"), Requirement("c<4.0")),
        ],
    }
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        c==3.0
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_resolvable_duplicate():
    buffer = io.StringIO()
    graph = {
        "": [("install", "a", Version("1.0"), Requirement("a"))],
        "a==1.0": [
            ("install", "b", Version("2.0"), Requirement("b>=2.0")),
            ("install", "c", Version("3.0"), Requirement("c<4.0")),
        ],
        "b==2.0": [("install", "c", Version("3.1"), Requirement("c>3.0"))],
    }
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        # NOTE: fromager selected c==3.1 from: ['3.0', '3.1']
        c==3.1
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_unresolvable_duplicate():
    buffer = io.StringIO()
    graph = {
        "": [("install", "a", Version("1.0"), Requirement("a"))],
        "a==1.0": [
            ("install", "b", Version("2.0"), Requirement("b>=2.0")),
            ("install", "c", Version("3.0"), Requirement("c==3.0")),
        ],
        "b==2.0": [("install", "c", Version("3.1"), Requirement("c>3.0"))],
    }
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        # ERROR: no single version of c met all requirements
        c==3.0
        c==3.1
        """).lstrip()
    assert expected == buffer.getvalue()
