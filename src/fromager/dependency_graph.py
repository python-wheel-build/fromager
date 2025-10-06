from __future__ import annotations

import dataclasses
import graphlib
import json
import logging
import pathlib
import threading
import typing

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from .read import open_file_or_url
from .requirements_file import RequirementType

logger = logging.getLogger(__name__)

ROOT = ""


class DependencyEdgeDict(typing.TypedDict):
    req_type: str
    req: str
    key: str


class DependencyNodeDict(typing.TypedDict):
    download_url: str
    canonicalized_name: str
    version: str
    pre_built: bool
    edges: list[DependencyEdgeDict]


@dataclasses.dataclass(frozen=True, order=True, slots=True)
class DependencyNode:
    canonicalized_name: NormalizedName
    version: Version
    download_url: str = dataclasses.field(default="", compare=False)
    pre_built: bool = dataclasses.field(default=False, compare=False)
    # additional fields
    key: str = dataclasses.field(init=False, compare=False, repr=False)
    parents: list[DependencyEdge] = dataclasses.field(
        default_factory=list,
        init=False,
        compare=False,
        repr=False,
    )
    children: list[DependencyEdge] = dataclasses.field(
        default_factory=list,
        init=False,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.canonicalized_name == ROOT:
            # root has a special key
            object.__setattr__(self, "key", ROOT)
        else:
            object.__setattr__(
                self, "key", f"{self.canonicalized_name}=={self.version}"
            )

    def add_child(
        self,
        child: DependencyNode,
        req: Requirement,
        req_type: RequirementType,
    ) -> None:
        current_to_child_edge = DependencyEdge(
            req=req, req_type=req_type, destination_node=child
        )
        self.children.append(current_to_child_edge)
        child_to_current_edge = DependencyEdge(
            req=req, req_type=req_type, destination_node=self
        )
        # will create a cyclic dependency in memory, which will make it harder to garbage collect
        # not an issue for fromager since it is used as a short-lived process
        child.parents.append(child_to_current_edge)

    def to_dict(self) -> DependencyNodeDict:
        return {
            "download_url": self.download_url,
            "pre_built": self.pre_built,
            "version": str(self.version),
            "canonicalized_name": str(self.canonicalized_name),
            "edges": [edge.to_dict() for edge in self.children],
        }

    def get_incoming_install_edges(self) -> list[DependencyEdge]:
        return [
            edge for edge in self.parents if edge.req_type == RequirementType.INSTALL
        ]

    def get_outgoing_edges(
        self, req_name: str, req_type: RequirementType
    ) -> list[DependencyEdge]:
        return [
            edge
            for edge in self.children
            if canonicalize_name(edge.req.name) == canonicalize_name(req_name)
            and edge.req_type == req_type
        ]

    @classmethod
    def construct_root_node(cls) -> DependencyNode:
        return cls(
            canonicalize_name(ROOT),
            # version doesn't really matter for root
            Version("0"),
        )


@dataclasses.dataclass(frozen=True, order=True, slots=True)
class DependencyEdge:
    key: str = dataclasses.field(init=False, repr=True, compare=True)
    destination_node: DependencyNode = dataclasses.field(repr=False, compare=False)
    req: Requirement = dataclasses.field(repr=True, compare=True)
    req_type: RequirementType = dataclasses.field(repr=True, compare=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", self.destination_node.key)

    def to_dict(self) -> DependencyEdgeDict:
        return {
            "key": self.key,
            "req_type": str(self.req_type),
            "req": str(self.req),
        }


class DependencyGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, DependencyNode] = {}
        self.clear()

    @classmethod
    def from_file(
        cls,
        graph_file: pathlib.Path | str,
    ) -> DependencyGraph:
        with open_file_or_url(graph_file) as f:
            # TODO: add JSON validation to ensure it is a parsable graph json
            raw_graph = typing.cast(dict[str, dict], json.load(f))
            return cls.from_dict(raw_graph)

    @classmethod
    def from_dict(
        cls,
        graph_dict: dict[str, dict[str, typing.Any]],
    ) -> DependencyGraph:
        graph = cls()
        stack = [ROOT]
        visited = set()
        while stack:
            curr_key = stack.pop()
            if curr_key in visited:
                continue
            node_dict = typing.cast(DependencyNodeDict, graph_dict[curr_key])
            parent_name = parent_version = None
            if curr_key != ROOT:
                parent_name = canonicalize_name(node_dict["canonicalized_name"])
                parent_version = Version(node_dict["version"])
            for raw_edge in node_dict["edges"]:
                edge_dict = typing.cast(DependencyEdgeDict, raw_edge)
                destination_node_dict = typing.cast(
                    DependencyNodeDict, graph_dict[edge_dict["key"]]
                )
                graph.add_dependency(
                    parent_name=parent_name,
                    parent_version=parent_version,
                    req_type=RequirementType(edge_dict["req_type"]),
                    req=Requirement(edge_dict["req"]),
                    req_version=Version(destination_node_dict["version"]),
                    download_url=destination_node_dict["download_url"],
                    pre_built=destination_node_dict["pre_built"],
                )
                stack.append(edge_dict["key"])
            visited.add(curr_key)
        return graph

    def clear(self) -> None:
        self.nodes.clear()
        self.nodes[ROOT] = DependencyNode.construct_root_node()

    def _to_dict(self):
        raw_graph = {}
        stack = [self.nodes[ROOT]]
        visited = set()
        while stack:
            node = stack.pop()
            raw_graph[node.key] = node.to_dict()
            for child in node.children:
                if child.destination_node.key not in visited:
                    stack.append(child.destination_node)
            visited.add(node.key)
        return raw_graph

    def serialize(self, file_handle: typing.TextIO):
        raw_graph = self._to_dict()
        json.dump(raw_graph, file_handle, indent=2, default=str)

    def _add_node(
        self,
        req_name: NormalizedName,
        version: Version,
        download_url: str,
        pre_built: bool,
    ):
        new_node = DependencyNode(
            canonicalized_name=req_name,
            version=version,
            download_url=download_url,
            pre_built=pre_built,
        )
        # check if a node with that key already exists. if it does then use that
        node = self.nodes.get(new_node.key, new_node)
        # store the node in case we are using new_node
        self.nodes[node.key] = node
        return node

    def add_dependency(
        self,
        parent_name: NormalizedName | None,
        parent_version: Version | None,
        req_type: RequirementType,
        req: Requirement,
        req_version: Version,
        download_url: str = "",
        pre_built: bool = False,
    ) -> None:
        logger.debug(
            "recording %s dependency %s%s -> %s==%s",
            req_type,
            parent_name if parent_name else f"({RequirementType.TOP_LEVEL})",
            f"=={parent_version}" if parent_version else "",
            req.name,
            req_version,
        )

        node = self._add_node(
            req_name=canonicalize_name(req.name),
            version=req_version,
            download_url=download_url,
            pre_built=pre_built,
        )

        parent_key = ROOT if parent_name is None else f"{parent_name}=={parent_version}"
        if parent_key not in self.nodes:
            raise ValueError(
                f"Trying to add {node.key} to parent {parent_key} but {parent_key} does not exist"
            )

        self.nodes[parent_key].add_child(node, req=req, req_type=req_type)

    def get_dependency_edges(
        self, match_dep_types: list[RequirementType] | None = None
    ) -> typing.Iterable[DependencyEdge]:
        visited = set()
        for edge in self._depth_first_traversal(
            self.nodes[ROOT].children,
            set(),
            match_dep_types=match_dep_types,
        ):
            if edge.destination_node.key not in visited:
                yield edge
                visited.add(edge.destination_node.key)

    def get_install_dependencies(self) -> typing.Iterable[DependencyNode]:
        for edge in self.get_dependency_edges(
            match_dep_types=[RequirementType.INSTALL, RequirementType.TOP_LEVEL]
        ):
            yield edge.destination_node

    def get_nodes_by_name(self, req_name: str | None) -> list[DependencyNode]:
        if not req_name:
            return [self.nodes[ROOT]]
        return [
            node
            for node in self.get_all_nodes()
            if node.canonicalized_name == canonicalize_name(req_name)
        ]

    def get_root_node(self) -> DependencyNode:
        return self.nodes[ROOT]

    def get_all_nodes(self) -> typing.Iterable[DependencyNode]:
        return self.nodes.values()

    def get_install_dependency_versions(
        self,
    ) -> dict[NormalizedName, list[DependencyNode]]:
        all_versions: dict[NormalizedName, list[DependencyNode]] = {}
        for node in self.get_install_dependencies():
            all_versions.setdefault(node.canonicalized_name, []).append(node)
        return all_versions

    def _depth_first_traversal(
        self,
        start_edges: list[DependencyEdge],
        visited: set[str],
        match_dep_types: list[RequirementType] | None = None,
    ) -> typing.Iterable[DependencyEdge]:
        for edge in start_edges:
            if edge.destination_node.key in visited:
                continue
            if match_dep_types and edge.req_type not in match_dep_types:
                continue
            visited.add(edge.destination_node.key)
            yield edge
            yield from self._depth_first_traversal(
                edge.destination_node.children, visited, match_dep_types
            )


class TrackingTopologicalSorter:
    """A thread-safe topological sorter that tracks nodes in progress

    ``TopologicalSorter.get_ready()`` returns each node only once. The
    tracking topological sorter keeps track which nodes are marked as done.
    The ``get_available()`` method returns nodes again and again, until
    they are marked as done. The graph is active until all nodes are marked
    as done.

    Individual nodes can be marked as exclusive nodes. ``get_available``
    treats exclusive nodes special and returns:

    1. one or more non-exclusive nodes
    2. exactly one exclusive node that is a predecessor of another node
    3. exactly one exclusive node

    The class uses a lock for ``is_activate`, ``get_available`, and ``done``,
    so the methods can be used from threading pool and future callback.
    """

    __slots__ = (
        "_dep_nodes",
        "_exclusive_nodes",
        "_in_progress_nodes",
        "_lock",
        "_topo",
    )

    def __init__(
        self,
        graph: typing.Mapping[DependencyNode, typing.Iterable[DependencyNode]]
        | None = None,
    ) -> None:
        self._topo: graphlib.TopologicalSorter[DependencyNode] = (
            graphlib.TopologicalSorter()
        )
        # set of nodes that are not done, yet
        self._in_progress_nodes: set[DependencyNode] = set()
        # set of nodes that are predecessors of other nodes
        self._dep_nodes: set[DependencyNode] = set()
        # dict of nodes -> priority; dependency: -1, leaf: +1
        self._exclusive_nodes: dict[DependencyNode, int] = {}
        self._lock = threading.Lock()
        if graph is not None:
            for node, predecessors in graph.items():
                self.add(node, *predecessors)

    @property
    def dependency_nodes(self) -> set[DependencyNode]:
        """Nodes that other nodes depend on"""
        return self._dep_nodes.copy()

    @property
    def exclusive_nodes(self) -> set[DependencyNode]:
        """Nodes that are marked as exclusive"""
        return set(self._exclusive_nodes)

    def add(
        self,
        node: DependencyNode,
        *predecessors: DependencyNode,
        exclusive: bool = False,
    ) -> None:
        """Add new node

        Can be called multiple times for a node to add more predecessors or
        to mark a node as exclusive. Exclusive nodes cannot be unmarked.
        """
        self._topo.add(node, *predecessors)
        self._dep_nodes.update(predecessors)
        if exclusive:
            self._exclusive_nodes[node] = 1

    def prepare(self) -> None:
        """Prepare and check for cyclic dependencies"""
        self._topo.prepare()
        for node in self._exclusive_nodes:
            if node in self._dep_nodes:
                # give dependency nodes a higher priority
                self._exclusive_nodes[node] = -1

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._in_progress_nodes) or self._topo.is_active()

    def __bool__(self) -> bool:
        return self.is_active()

    def get_available(self) -> set[DependencyNode]:
        """Get available nodes

        A node can be returned multiple times until it is marked as 'done'.
        """
        with self._lock:
            # get ready nodes, update in progress nodes.
            ready = self._topo.get_ready()
            self._in_progress_nodes.update(ready)

            # get and prefer non-exclusive nodes. Exclusive nodes are
            # 'heavy' nodes, that that a long time to build. Start with
            # 'light' nodes first.
            exclusive_nodes = self._exclusive_nodes
            non_exclusive = self._in_progress_nodes.difference(exclusive_nodes)
            if non_exclusive:
                # set.difference() returns a new set object
                return non_exclusive

            # return a single exclusive node, prefer nodes that are a
            # dependency of other nodes.
            exclusive = self._in_progress_nodes.intersection(exclusive_nodes)
            exclusive_list = sorted(
                exclusive,
                key=lambda node: (exclusive_nodes[node], node),
            )
            return {exclusive_list[0]}

    def done(self, *nodes: DependencyNode) -> None:
        """Mark nodes as done"""
        with self._lock:
            self._in_progress_nodes.difference_update(nodes)
            self._topo.done(*nodes)

    def static_batches(self) -> typing.Iterable[set[DependencyNode]]:
        self.prepare()
        while self.is_active():
            nodes = self.get_available()
            yield nodes
            self.done(*nodes)
