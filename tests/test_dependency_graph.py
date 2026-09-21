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


def mknode(name: str, version: str = "1.0", **kwargs: typing.Any) -> DependencyNode:
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


def _build_graph(*edges: tuple[str, str, str]) -> DependencyGraph:
    """Build a DependencyGraph from (parent, child, req_type) triples.

    Use "ROOT" as parent name for top-level dependencies.
    """
    graph = DependencyGraph()
    for parent_name, child_name, req_type_str in edges:
        parent_n = None if parent_name == "ROOT" else canonicalize_name(parent_name)
        parent_v = None if parent_name == "ROOT" else Version("1.0")
        graph.add_dependency(
            parent_name=parent_n,
            parent_version=parent_v,
            req_type=RequirementType(req_type_str),
            req=Requirement(f"{child_name}==1.0"),
            req_version=Version("1.0"),
        )
    return graph


def test_remove_dependency_basic() -> None:
    """Removing a leaf node cleans it from nodes and parent's children."""
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("a", "b", "install"),
    )
    assert "b==1.0" in graph.nodes
    assert len(graph.nodes["a==1.0"].children) == 1

    graph.remove_dependency(canonicalize_name("b"), Version("1.0"))

    assert "b==1.0" not in graph.nodes
    assert len(graph.nodes["a==1.0"].children) == 0


def test_remove_dependency_cascades_orphans() -> None:
    """Removing a node recursively removes its orphaned descendants."""
    # ROOT -> a -> b -> c  (linear chain)
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("a", "b", "install"),
        ("b", "c", "install"),
    )
    assert "a==1.0" in graph.nodes
    assert "b==1.0" in graph.nodes
    assert "c==1.0" in graph.nodes

    graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert "a==1.0" not in graph.nodes
    assert "b==1.0" not in graph.nodes
    assert "c==1.0" not in graph.nodes
    assert len(graph) == 0


def test_remove_dependency_keeps_shared_children() -> None:
    """Children with other parents are kept; only the stale parent edge is removed."""
    # ROOT -> a -> shared
    # ROOT -> b -> shared
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("ROOT", "b", "toplevel"),
        ("a", "shared", "install"),
        ("b", "shared", "install"),
    )
    shared_node = graph.nodes["shared==1.0"]
    assert len(shared_node.parents) == 2

    graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert "a==1.0" not in graph.nodes
    assert "shared==1.0" in graph.nodes
    assert len(shared_node.parents) == 1
    assert shared_node.parents[0].destination_node.key == "b==1.0"


def test_remove_dependency_diamond_sequential() -> None:
    """Diamond: shared child survives first removal, cleaned up by second."""
    # ROOT -> a -> c
    # ROOT -> b -> c
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("ROOT", "b", "toplevel"),
        ("a", "c", "install"),
        ("b", "c", "install"),
    )

    graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert "a==1.0" not in graph.nodes
    assert "c==1.0" in graph.nodes
    assert len(graph.nodes["c==1.0"].parents) == 1

    graph.remove_dependency(canonicalize_name("b"), Version("1.0"))

    assert "b==1.0" not in graph.nodes
    assert "c==1.0" not in graph.nodes
    assert len(graph) == 0


def test_remove_dependency_already_removed_child() -> None:
    """Removing a node whose child was already removed is safe."""
    # ROOT -> a -> b -> c
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("a", "b", "install"),
        ("b", "c", "install"),
    )

    graph.remove_dependency(canonicalize_name("c"), Version("1.0"))
    graph.remove_dependency(canonicalize_name("b"), Version("1.0"))

    assert "b==1.0" not in graph.nodes
    assert "c==1.0" not in graph.nodes
    assert "a==1.0" in graph.nodes
    assert len(graph.nodes["a==1.0"].children) == 0


def test_remove_dependency_mid_graph_cascades() -> None:
    """Removing a mid-graph node cascades to its exclusive subtree.

    Verifies both that orphaned nodes are gone and that the surviving
    tree structure (edges in both directions) is fully intact.
    """
    # ROOT -> a -> b -> d
    #              b -> e
    #         a -> c
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("a", "b", "install"),
        ("a", "c", "install"),
        ("b", "d", "install"),
        ("b", "e", "install"),
    )

    graph.remove_dependency(canonicalize_name("b"), Version("1.0"))

    # Removed subtree is gone
    assert "b==1.0" not in graph.nodes
    assert "d==1.0" not in graph.nodes
    assert "e==1.0" not in graph.nodes

    # Exactly ROOT, a, c remain
    assert set(graph.nodes.keys()) == {"", "a==1.0", "c==1.0"}

    # ROOT -> a edge intact
    root = graph.get_root_node()
    assert len(root.children) == 1
    assert root.children[0].destination_node.key == "a==1.0"

    # a -> c is the only surviving child edge, and a's parent is ROOT
    node_a = graph.nodes["a==1.0"]
    assert len(node_a.children) == 1
    assert node_a.children[0].destination_node.key == "c==1.0"
    assert len(node_a.parents) == 1
    assert node_a.parents[0].destination_node.key == ""

    # c has a as parent, no children
    node_c = graph.nodes["c==1.0"]
    assert len(node_c.children) == 0
    assert len(node_c.parents) == 1
    assert node_c.parents[0].destination_node.key == "a==1.0"


def test_remove_dependency_shared_child_kept_by_other_subtree() -> None:
    """Shared child and its descendants survive when kept alive by another subtree.

    ROOT -> a -> b -> d
           a -> c -> d
    ROOT -> e -> c

    Removing a should remove a, b; c and d survive because e still parents c.
    """
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("ROOT", "e", "toplevel"),
        ("a", "b", "install"),
        ("a", "c", "install"),
        ("b", "d", "install"),
        ("c", "d", "install"),
        ("e", "c", "install"),
    )

    graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert "a==1.0" not in graph.nodes
    assert "b==1.0" not in graph.nodes
    assert "c==1.0" in graph.nodes
    assert "d==1.0" in graph.nodes
    assert "e==1.0" in graph.nodes

    node_c = graph.nodes["c==1.0"]
    assert len(node_c.parents) == 1
    assert node_c.parents[0].destination_node.key == "e==1.0"
    assert len(node_c.children) == 1
    assert node_c.children[0].destination_node.key == "d==1.0"

    node_d = graph.nodes["d==1.0"]
    assert len(node_d.parents) == 1
    assert node_d.parents[0].destination_node.key == "c==1.0"


def test_remove_dependency_cascades_through_diamond() -> None:
    """Single removal cascades through a diamond, removing all orphans.

    ROOT -> a -> b -> d
           a -> c -> d

    Removing a orphans b and c; as both are removed, d loses all parents
    and is also removed.
    """
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("a", "b", "install"),
        ("a", "c", "install"),
        ("b", "d", "install"),
        ("c", "d", "install"),
    )

    graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert "a==1.0" not in graph.nodes
    assert "b==1.0" not in graph.nodes
    assert "c==1.0" not in graph.nodes
    assert "d==1.0" not in graph.nodes
    assert len(graph) == 0


def test_remove_dependency_nonexistent() -> None:
    """Removing a node not in the graph is a no-op."""
    graph = _build_graph(("ROOT", "a", "toplevel"))
    node_count = len(graph.nodes)

    removed = graph.remove_dependency(canonicalize_name("nonexistent"), Version("1.0"))

    assert removed == []
    assert len(graph.nodes) == node_count


def test_remove_dependency_returns_removed_nodes() -> None:
    graph = _build_graph(
        ("ROOT", "a", "toplevel"),
        ("ROOT", "d", "toplevel"),
        ("a", "b", "build-system"),
        ("b", "c", "build-backend"),
        ("a", "shared", "install"),
        ("d", "shared", "install"),
    )

    removed = graph.remove_dependency(canonicalize_name("a"), Version("1.0"))

    assert [n.key for n in removed] == ["a==1.0", "b==1.0", "c==1.0"]
    assert "shared==1.0" in graph.nodes
