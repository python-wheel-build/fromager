import io
import pathlib
import textwrap

from packaging.requirements import Requirement

from fromager import dependency_graph
from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(["a"], [])
    assert [Requirement("a")] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(["a", "b"], [])
    assert [Requirement("a"), Requirement("b")] == requirements


def test_get_requirements_args_and_file(tmp_path: pathlib.Path):
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("c\n")
    requirements = bootstrap._get_requirements_from_args(
        ["a", "b"], [str(requirements_file)]
    )
    assert [
        Requirement("a"),
        Requirement("b"),
        Requirement("c"),
    ] == requirements


def test_ignore_based_on_marker():
    requirements = bootstrap._get_requirements_from_args(
        ['foo; python_version<"3.9"'], []
    )
    assert [] == requirements


def test_write_constraints_file_simple():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c<4.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        c==3.0
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_resolvable_duplicate():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c<4.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [{"key": "c==3.1", "req_type": "install", "req": "c>3.0"}],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
        "c==3.1": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
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
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c==3.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [{"key": "c==3.1", "req_type": "install", "req": "c>3.0"}],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
        "c==3.1": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        # ERROR: no single version of c met all requirements
        c==3.0
        c==3.1
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_duplicates():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [
                {"key": "a==1.0", "req_type": "install", "req": "a"},
                {"key": "d==1.0", "req_type": "install", "req": "d"},
            ],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "c==3.0", "req_type": "install", "req": "c<=3.0"},
            ],
        },
        "d==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "c==3.1", "req_type": "install", "req": "c>=3.0"},
            ],
        },
        "c==3.0": {  # transformers 4.46
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [{"key": "b==2.0", "req_type": "install", "req": "b<2.1,>=2.0"}],
        },
        "c==3.1": {  # transformers 4.47
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [{"key": "b==2.1", "req_type": "install", "req": "b<2.2,>=2.1"}],
        },
        "b==2.0": {  # tokenizer
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [],
        },
        "b==2.1": {  # tokenizer
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.1",
            "canonicalized_name": "b",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    assert bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        # NOTE: fromager selected b==2.0 from: ['2.0', '2.1']
        b==2.0
        # NOTE: fromager selected c==3.0 from: ['3.0', '3.1']
        c==3.0
        d==1.0
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_multiples():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [
                {
                    "key": "a==2.7.0",
                    "req_type": "toplevel",
                    "req": "a==2.7.0",
                },
                {
                    "key": "b==0.26.1",
                    "req_type": "toplevel",
                    "req": "b==0.26.1",
                },
            ],
        },
        "b==0.26.1": {
            "download_url": "",
            "pre_built": False,
            "version": "0.26.1",
            "canonicalized_name": "b",
            "edges": [],
        },
        "b==0.26.2": {
            "download_url": "",
            "pre_built": False,
            "version": "0.26.2",
            "canonicalized_name": "b",
            "edges": [],
        },
        "a==2.7.0": {
            "download_url": "",
            "pre_built": False,
            "version": "2.7.0",
            "canonicalized_name": "a",
            "edges": [
                {
                    "key": "b==0.26.2",
                    "req_type": "install",
                    "req": "b<0.27.0,>=0.26.1",
                },
            ],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    assert bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==2.7.0
        # NOTE: fromager selected b==0.26.2 from: ['0.26.1', '0.26.2']
        b==0.26.2
        """).lstrip()
    assert expected == buffer.getvalue()
