from __future__ import annotations

import dataclasses
import json
import logging
import pathlib
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
    # not set in older graph files
    constraint: typing.NotRequired[str | None]
    edges: list[DependencyEdgeDict]


@dataclasses.dataclass(frozen=True, order=True, slots=True)
class DependencyNode:
    canonicalized_name: NormalizedName
    version: Version
    download_url: str = dataclasses.field(default="", compare=False)
    pre_built: bool = dataclasses.field(default=False, compare=False)
    constraint: Requirement | None = dataclasses.field(default=None, compare=False)
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
            "constraint": str(self.constraint) if self.constraint else None,
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

    def iter_build_requirements(self) -> typing.Iterable[DependencyNode]:
        """Get all unique, recursive build requirements

        Yield all direct and indirect requirements to build the dependency.
        Includes direct build dependencies and their recursive **install**
        requirements.

        The result is equivalent to the set of ``[build-system].requires``
        plus all ``Requires-Dist`` of build system requirements -- all
        packages in the build environment.
        """
        visited: set[str] = set()
        # The outer loop iterates over all children and picks
        # direct build requirements. For each build requirement, it traverses
        # all children and recursively get their install requirements
        # (depth first).
        for edge in self.children:
            if edge.key in visited:
                # optimization: don't traverse visited nodes
                continue
            if not edge.req_type.is_build_requirement:
                # not a build requirement
                continue
            visited.add(edge.key)
            # it's a new ``[build-system].requires``.
            yield edge.destination_node
            # recursively get install dependencies of this build dep (depth first).
            for install_edge in self._traverse_install_requirements(
                edge.destination_node.children, visited
            ):
                yield install_edge.destination_node

    def iter_install_requirements(self) -> typing.Iterable[DependencyNode]:
        """Get all unique, recursive install requirements"""
        visited: set[str] = set()
        for edge in self._traverse_install_requirements(self.children, visited):
            yield edge.destination_node

    def _traverse_install_requirements(
        self,
        start_edges: list[DependencyEdge],
        visited: set[str],
    ) -> typing.Iterable[DependencyEdge]:
        for edge in start_edges:
            if edge.key in visited:
                continue
            if not edge.req_type.is_install_requirement:
                continue
            visited.add(edge.destination_node.key)
            yield edge
            yield from self._traverse_install_requirements(
                edge.destination_node.children, visited
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
                constraint_value: str | None = destination_node_dict.get("constraint")
                constraint: Requirement | None = (
                    Requirement(constraint_value) if constraint_value else None
                )
                graph.add_dependency(
                    parent_name=parent_name,
                    parent_version=parent_version,
                    req_type=RequirementType(edge_dict["req_type"]),
                    req=Requirement(edge_dict["req"]),
                    req_version=Version(destination_node_dict["version"]),
                    download_url=destination_node_dict["download_url"],
                    pre_built=destination_node_dict["pre_built"],
                    constraint=constraint,
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
        constraint: Requirement | None,
    ):
        new_node = DependencyNode(
            canonicalized_name=req_name,
            version=version,
            download_url=download_url,
            pre_built=pre_built,
            constraint=constraint,
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
        constraint: Requirement | None = None,
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
            constraint=constraint,
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
