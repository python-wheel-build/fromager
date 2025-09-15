import graphlib

import pathlib

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.dependency_graph import DependencyGraph, DependencyNode
from fromager.requirements_file import RequirementType


@pytest.fixture
def depgraph(testdata_path: pathlib.Path) -> DependencyGraph:
    return DependencyGraph.from_file(testdata_path / "graph.json")


def mknode(name: str, version: str = "1.0", **kwargs) -> DependencyNode:
    return DependencyNode(canonicalize_name(name), Version(version), **kwargs)


def get_build_graph(*nodes: DependencyNode) -> list[list[str]]:
    topo: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
    for node in nodes:
        build_deps = [n.canonicalized_name for n in node.iter_build_requirements()]
        topo.add(node.canonicalized_name, *build_deps)
    topo.prepare()
    steps: list[list[str]] = []
    while topo.is_active():
        ready = topo.get_ready()
        steps.append(sorted(ready))
        topo.done(*ready)
    return steps


def test_compare() -> None:
    a_10 = mknode("a", "1.0")
    a_20 = mknode("a", "2.0")
    b = mknode("b", "1.0")
    assert a_10 == a_10
    assert not a_10 == a_20
    assert a_10 != a_20
    assert a_10 != b
    assert a_10 == mknode("a", "1.0")
    assert a_10 < a_20
    assert a_10 <= a_10
    assert a_10 >= a_10
    assert b > a_10
    assert b > a_20


def test_hash() -> None:
    a_10 = mknode("a", "1.0")
    a_20 = mknode("a", "2.0")
    b = mknode("b", "1.0")
    s = {a_10, a_10, a_20}
    assert s == {a_10, a_20}
    assert a_10 in s
    assert b not in s


def test_iter_requirements() -> None:
    a = mknode("a")
    # install requirements of a
    b = mknode("b")
    # build requirement of a
    c = mknode("c")
    # build requirement of c
    d = mknode("d")
    # install requirement of b and c
    e = mknode("e")
    # build requirement of a and c
    f = mknode("f")

    a.add_child(b, Requirement(b.canonicalized_name), RequirementType.INSTALL)
    a.add_child(c, Requirement(c.canonicalized_name), RequirementType.BUILD_BACKEND)
    a.add_child(c, Requirement(c.canonicalized_name), RequirementType.BUILD_SYSTEM)
    a.add_child(f, Requirement(c.canonicalized_name), RequirementType.BUILD_SYSTEM)
    b.add_child(e, Requirement(b.canonicalized_name), RequirementType.INSTALL)
    c.add_child(d, Requirement(d.canonicalized_name), RequirementType.BUILD_SYSTEM)
    c.add_child(e, Requirement(e.canonicalized_name), RequirementType.INSTALL)
    c.add_child(f, Requirement(f.canonicalized_name), RequirementType.BUILD_BACKEND)

    assert sorted(a.iter_install_requirements()) == [b, e]
    assert sorted(a.iter_build_requirements()) == [c, e, f]
    assert sorted(b.iter_install_requirements()) == [e]
    assert sorted(b.iter_build_requirements()) == []
    assert sorted(c.iter_install_requirements()) == [e]
    assert sorted(c.iter_build_requirements()) == [d, f]

    build_graph = get_build_graph(a, b, c, d, e, f)
    assert build_graph == [
        # no build requirements, B and E can be built in parallel, as
        # B just has an install requirement on E.
        ["b", "d", "e", "f"],
        # C needs D, F to build.
        ["c"],
        # A needs C, E, F.
        ["a"],
    ]


def test_pr759_discussion() -> None:
    a = mknode("a")
    b = mknode("b")
    c = mknode("c")
    d = mknode("d")
    # A needs B to build.
    a.add_child(b, Requirement(c.canonicalized_name), RequirementType.BUILD_BACKEND)
    # B needs C to build.
    b.add_child(c, Requirement(c.canonicalized_name), RequirementType.BUILD_BACKEND)
    # B needs D to install.
    b.add_child(d, Requirement(c.canonicalized_name), RequirementType.INSTALL)

    assert sorted(a.iter_build_requirements()) == [b, d]
    assert sorted(b.iter_build_requirements()) == [c]
    assert sorted(c.iter_build_requirements()) == []
    assert sorted(d.iter_build_requirements()) == []

    build_graph = get_build_graph(a, b, c, d)
    assert build_graph == [["c", "d"], ["b"], ["a"]]

    # add more nodes
    e = mknode("e")
    f = mknode("f")
    # D needs E to install.
    d.add_child(e, Requirement(c.canonicalized_name), RequirementType.INSTALL)
    # E needs F to build.
    e.add_child(f, Requirement(c.canonicalized_name), RequirementType.BUILD_BACKEND)

    # build requirements
    assert sorted(a.iter_build_requirements()) == [b, d, e]
    assert sorted(b.iter_build_requirements()) == [c]
    assert sorted(c.iter_build_requirements()) == []
    assert sorted(d.iter_build_requirements()) == []
    assert sorted(e.iter_build_requirements()) == [f]

    build_graph = get_build_graph(a, b, c, d, e, f)
    assert build_graph == [
        # D, C, F don't have build requirements
        ["c", "d", "f"],
        # B needs C, E needs F
        ["b", "e"],
        # A needs B, D, E
        ["a"],
    ]

    # install requirements
    assert sorted(a.iter_install_requirements()) == []
    # E is an indirect install dependency
    assert sorted(b.iter_install_requirements()) == [d, e]
    assert sorted(c.iter_install_requirements()) == []
    assert sorted(d.iter_install_requirements()) == [e]
    assert sorted(e.iter_install_requirements()) == []
    assert sorted(f.iter_install_requirements()) == []


def test_dependency_graph(depgraph: DependencyGraph) -> None:
    assert set(depgraph.nodes) == {
        "",
        "cython==3.1.1",
        "flit-core==3.12.0",
        "imapautofiler==1.14.0",
        "imapclient==3.0.1",
        "jaraco-classes==3.4.0",
        "jaraco-context==6.0.1",
        "jaraco-functools==4.1.0",
        "jinja2==3.1.6",
        "keyring==25.6.0",
        "markupsafe==3.0.2",
        "more-itertools==10.7.0",
        "packaging==25.0",
        "pyyaml==6.0.2",
        "setuptools-scm==8.3.1",
        "setuptools==80.8.0",
        "wheel==0.46.1",
    }


def test_dependency_graph_iter_requirements(depgraph: DependencyGraph) -> None:
    nodes = depgraph.get_nodes_by_name("cython")
    assert len(nodes) == 1
    cython = nodes[0]
    assert sorted(node.key for node in cython.iter_build_requirements()) == [
        "setuptools==80.8.0"
    ]
    assert sorted(node.key for node in cython.iter_install_requirements()) == []

    nodes = depgraph.get_nodes_by_name("pyyaml")
    assert len(nodes) == 1
    pyyaml = nodes[0]
    assert sorted(node.key for node in pyyaml.iter_build_requirements()) == [
        "cython==3.1.1",
        "setuptools==80.8.0",
        "wheel==0.46.1",
    ]
    assert sorted(node.key for node in pyyaml.iter_install_requirements()) == []


def test_build_graph(depgraph: DependencyGraph) -> None:
    steps: list[list[str]] = []

    topo = depgraph.get_build_topology()
    while topo.is_active():
        nodes: tuple[DependencyNode, ...] = topo.get_ready()
        steps.append(sorted(node.key for node in nodes))
        topo.done(*nodes)

    assert steps == [
        [
            # build systems can bootstrap without external dependencies
            "flit-core==3.12.0",
            "setuptools==80.8.0",
        ],
        [
            # packages that just depend on 'flit-core' or 'setuptools'
            "cython==3.1.1",
            "imapclient==3.0.1",
            "jinja2==3.1.6",
            "markupsafe==3.0.2",
            "more-itertools==10.7.0",
            "packaging==25.0",
        ],
        [
            # the two packages depend on 'packaging'
            "setuptools-scm==8.3.1",
            "wheel==0.46.1",
        ],
        [
            # final set depends on 'setuptools-scm' or 'wheel'
            "imapautofiler==1.14.0",
            "jaraco-classes==3.4.0",
            "jaraco-context==6.0.1",
            "jaraco-functools==4.1.0",
            "keyring==25.6.0",
            "pyyaml==6.0.2",
        ],
    ]
