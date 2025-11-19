import dataclasses
import graphlib
import pathlib
import threading
import time
import typing

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import context
from fromager.dependency_graph import (
    DependencyGraph,
    DependencyNode,
    TrackingTopologicalSorter,
)
from fromager.requirements_file import RequirementType


def mknode(name: str, version: str = "1.0", **kwargs) -> DependencyNode:
    return DependencyNode(canonicalize_name(name), Version(version), **kwargs)


def test_dependencynode_compare() -> None:
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


def test_dependencynode_hash() -> None:
    a_10 = mknode("a", "1.0")
    a_20 = mknode("a", "2.0")
    b = mknode("b", "1.0")
    s = {a_10, a_10, a_20}
    assert s == {a_10, a_20}
    assert a_10 in s
    assert b not in s

    s = {mknode("a"), mknode("a")}
    assert len(s) == 1
    assert s == {mknode("a")}


def test_dependencynode_dataclass() -> None:
    a = mknode("a", "1.0")
    assert a.canonicalized_name == "a"
    assert a.version == Version("1.0")
    assert a.key == "a==1.0"
    assert (
        repr(a)
        == "DependencyNode(canonicalized_name='a', version=<Version('1.0')>, download_url='', pre_built=False, constraint=None)"
    )
    assert a.requirement == Requirement("a==1.0")

    with pytest.raises(dataclasses.FrozenInstanceError):
        a.version = Version("2.0")  # type: ignore[misc]
    with pytest.raises((TypeError, AttributeError)):
        a.new_attribute = None  # type: ignore[attr-defined]

    root = DependencyNode.construct_root_node()
    assert root.canonicalized_name == ""
    assert root.version == Version("0.0")
    assert root.key == ""
    with pytest.raises(RuntimeError):
        assert root.requirement


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


def test_tracking_topology_sorter() -> None:
    a = mknode("a")
    b = mknode("b")
    c = mknode("c")
    d = mknode("d")
    e = mknode("e")
    f = mknode("f")

    graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
    graph = {
        a: [b, c],
        b: [c, d],
        d: [e],
        f: [d],
    }

    topo = TrackingTopologicalSorter(graph)
    topo.prepare()

    assert topo.dependency_nodes == {b, c, d, e}
    assert topo.exclusive_nodes == set()
    # properties return new objects
    assert topo.dependency_nodes is not topo.dependency_nodes
    assert topo.exclusive_nodes is not topo.exclusive_nodes

    processed: list[DependencyNode] = []
    while topo.is_active():
        ready = sorted(topo.get_available())
        r0 = ready[0]
        processed.append(r0)
        topo.done(r0)
    # c and e have no dependency
    # d depends on e
    # b after d
    # f after d, but sorting pushes it after a
    # a on b
    assert processed == [c, e, d, b, a, f]

    topo = TrackingTopologicalSorter(graph)
    assert topo.dependency_nodes == {b, c, d, e}
    assert topo.exclusive_nodes == set()
    batches = list(topo.static_batches())
    assert batches == [
        {c, e},
        {d},
        {b, f},
        {a},
    ]

    topo = TrackingTopologicalSorter(graph)
    # mark b as exclusive
    topo.add(b, exclusive=True)
    assert topo.dependency_nodes == {b, c, d, e}
    assert topo.exclusive_nodes == {b}
    batches = list(topo.static_batches())
    assert batches == [
        {c, e},
        {d},
        {f},
        {b},
        {a},
    ]

    # call get_available() multiple times
    topo = TrackingTopologicalSorter(graph)
    topo.prepare()
    assert topo.get_available() == {c, e}
    assert topo.get_available() == {c, e}
    assert topo.get_available() == {c, e}
    topo.done(c, e)
    assert topo.get_available() == {d}


def test_tracking_topology_sorter_cyclic_error() -> None:
    # cyclic graph
    a = mknode("a")
    b = mknode("b")

    graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
    graph = {
        a: [b],
        b: [a],
    }

    topo = TrackingTopologicalSorter(graph)
    with pytest.raises(graphlib.CycleError):
        topo.prepare()


def test_tracking_topology_sorter_not_passed_out_error() -> None:
    # mark node as ready before it was passed out
    a = mknode("a")
    b = mknode("b")
    graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
    graph = {
        a: [b],
        b: [],
    }
    topo = TrackingTopologicalSorter(graph)
    topo.prepare()
    with pytest.raises(ValueError) as excinfo:
        topo.done(a)
    assert "was not passed out" in str(excinfo.value)


def test_tracking_topology_sorter_not_active_error() -> None:
    # call get_available without checking is_active
    a = mknode("a")
    graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
    graph = {
        a: [],
    }
    topo = TrackingTopologicalSorter(graph)
    topo.prepare()
    done = topo.get_available()
    topo.done(*done)
    assert not topo.is_active()
    with pytest.raises(ValueError) as excinfo:
        topo.get_available()
    assert "topology is not active" in str(excinfo.value)


def node2str(nodes: set[DependencyNode]) -> set[str]:
    return {node.key for node in nodes}


def test_e2e_parallel_graph(
    tmp_context: context.WorkContext, e2e_path: pathlib.Path
) -> None:
    graph = DependencyGraph.from_file(e2e_path / "build-parallel" / "graph.json")
    assert len(graph) == 16

    topo = graph.get_build_topology(tmp_context)
    assert node2str(topo.dependency_nodes) == {
        "cython==3.1.1",
        "flit-core==3.12.0",
        "packaging==25.0",
        "setuptools-scm==8.3.1",
        "setuptools==80.8.0",
        "wheel==0.46.1",
    }

    steps = [node2str(batch) for batch in topo.static_batches()]
    assert steps == [
        {
            "flit-core==3.12.0",
            "setuptools==80.8.0",
        },
        {
            "cython==3.1.1",
            "imapclient==3.0.1",
            "jinja2==3.1.6",
            "markupsafe==3.0.2",
            "more-itertools==10.7.0",
            "packaging==25.0",
        },
        {
            "setuptools-scm==8.3.1",
            "wheel==0.46.1",
        },
        {
            "imapautofiler==1.14.0",
            "jaraco-classes==3.4.0",
            "jaraco-context==6.0.1",
            "jaraco-functools==4.1.0",
            "keyring==25.6.0",
            "pyyaml==6.0.2",
        },
    ]

    # same graph, but mark cython as exclusive
    topo = graph.get_build_topology(tmp_context)
    node = graph.nodes["cython==3.1.1"]
    topo.add(node, exclusive=True)

    steps = [node2str(batch) for batch in topo.static_batches()]
    assert steps == [
        {
            "flit-core==3.12.0",
            "setuptools==80.8.0",
        },
        {
            "imapclient==3.0.1",
            "jinja2==3.1.6",
            "markupsafe==3.0.2",
            "more-itertools==10.7.0",
            "packaging==25.0",
        },
        {
            "setuptools-scm==8.3.1",
            "wheel==0.46.1",
        },
        {
            "imapautofiler==1.14.0",
            "jaraco-classes==3.4.0",
            "jaraco-context==6.0.1",
            "jaraco-functools==4.1.0",
            "keyring==25.6.0",
        },
        {
            "cython==3.1.1",
        },
        {
            "pyyaml==6.0.2",
        },
    ]


def test_tracking_topology_sorter_concurrent_access() -> None:
    """Test thread safety with concurrent get_available() and done() calls.
    EXPECTED: Should work correctly with multiple threads
    """
    nodes = [mknode(f"node_{i}") for i in range(20)]

    graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
    graph_dict = {}
    for i in range(1, 20):
        graph_dict[nodes[i]] = [nodes[i - 1]]
    graph_dict[nodes[0]] = []
    graph = graph_dict

    topo = TrackingTopologicalSorter(graph)
    topo.prepare()

    errors: list[Exception] = []
    processed: list[DependencyNode] = []
    process_lock = threading.Lock()

    def worker() -> None:
        try:
            while True:
                if not topo.is_active():
                    break

                try:
                    available = topo.get_available()
                except ValueError as e:
                    if "topology is not active" in str(e):
                        break
                    raise

                if not available:
                    time.sleep(0.0001)
                    continue

                node = sorted(available)[0]
                time.sleep(0.0001)

                with process_lock:
                    if node not in processed:
                        processed.append(node)
                        topo.done(node)

        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=5.0)
        if t.is_alive():
            errors.append(TimeoutError("Thread did not complete in time"))

    assert not errors, f"Thread safety violated with {len(errors)} errors: {errors}"
    assert len(processed) == 20, f"Expected 20 nodes processed, got {len(processed)}"
    assert not topo.is_active()


def test_tracking_topology_sorter_empty_graph() -> None:
    """Test with empty graph."""
    topo = TrackingTopologicalSorter()
    topo.prepare()

    assert not topo.is_active()

    with pytest.raises(ValueError) as excinfo:
        topo.get_available()
    assert "topology is not active" in str(excinfo.value)
