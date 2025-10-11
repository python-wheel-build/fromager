import dataclasses
import typing

import pytest
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.dependency_graph import DependencyNode, TrackingTopologicalSorter


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


def test_dependencynode_dataclass():
    a = mknode("a", "1.0")
    assert a.canonicalized_name == "a"
    assert a.version == Version("1.0")
    assert a.key == "a==1.0"
    assert (
        repr(a)
        == "DependencyNode(canonicalized_name='a', version=<Version('1.0')>, download_url='', pre_built=False)"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.version = Version("2.0")
    with pytest.raises((TypeError, AttributeError)):
        a.new_attribute = None

    root = DependencyNode.construct_root_node()
    assert root.canonicalized_name == ""
    assert root.version == Version("0.0")
    assert root.key == ""


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
