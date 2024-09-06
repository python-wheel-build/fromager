import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import dependency_graph, requirements_file

raw_graph = {
    "": {
        "download_url": "",
        "pre_built": False,
        "version": "0",
        "canonicalized_name": "",
        "edges": [{"key": "a==2.0", "req_type": "install", "req": "a==2.0"}],
    },
    "a==2.0": {
        "download_url": "url",
        "pre_built": False,
        "version": "2.0",
        "canonicalized_name": "a",
        "edges": [
            {"key": "b==3.0", "req_type": "build-system", "req": "b==3.0"},
            {"key": "c==4.0", "req_type": "build-backend", "req": "c==4.0"},
        ],
    },
    "b==3.0": {
        "download_url": "url for b",
        "pre_built": False,
        "version": "3.0",
        "canonicalized_name": "b",
        "edges": [
            {"key": "c==4.0", "req_type": "build-sdist", "req": "c<=4.0"},
        ],
    },
    "c==4.0": {
        "download_url": "url for c",
        "pre_built": False,
        "version": "4.0",
        "canonicalized_name": "c",
        "edges": [],
    },
}


def test_graph_add_dependency():
    graph = dependency_graph.DependencyGraph()
    # top level dependency
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("a==2.0"),
        req_version=Version("2.0"),
        download_url="url",
    )

    # children for toplevel
    graph.add_dependency(
        parent_name=canonicalize_name("a"),
        parent_version=Version("2.0"),
        req_type=requirements_file.RequirementType.BUILD_SYSTEM,
        req=Requirement("b==3.0"),
        req_version=Version("3.0"),
        download_url="url for b",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("a"),
        parent_version=Version("2.0"),
        req_type=requirements_file.RequirementType.BUILD_BACKEND,
        req=Requirement("c==4.0"),
        req_version=Version("4.0"),
        download_url="url for c",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("b"),
        parent_version=Version("3.0"),
        req_type=requirements_file.RequirementType.BUILD_SDIST,
        req=Requirement("c<=4.0"),
        req_version=Version("4.0"),
        download_url="url for c",
    )

    with pytest.raises(ValueError):
        # add dependency for a parent that doesn't exist
        graph.add_dependency(
            parent_name=canonicalize_name("z"),
            parent_version=Version("3.0"),
            req_type=requirements_file.RequirementType.BUILD_SYSTEM,
            req=Requirement("b==3.0"),
            req_version=Version("3.0"),
            download_url="url for b",
        )

    assert graph._to_dict() == raw_graph


def test_graph_from_dict():
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    assert graph._to_dict() == raw_graph


def test_get_install_dependencies():
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    graph.add_dependency(
        parent_name=canonicalize_name("a"),
        parent_version=Version("2.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("d>=4.0"),
        req_version=Version("6.0"),
        download_url="url for d",
    )

    # shouldn't be picked up by get_install_dependencies since b only appears as a build req
    graph.add_dependency(
        parent_name=canonicalize_name("b"),
        parent_version=Version("3.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("e>=4.0"),
        req_version=Version("6.0"),
        download_url="url for e",
    )

    install_nodes = [
        f"{node.to_dict()['canonicalized_name']}=={node.to_dict()['version']}"
        for node in graph.get_install_dependencies()
    ]
    assert install_nodes == ["a==2.0", "d==6.0"]

    # make b appear as install dependency
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("b<4.0"),
        req_version=Version("3.0"),
        download_url="url for b",
    )

    install_nodes = [
        f"{node.to_dict()['canonicalized_name']}=={node.to_dict()['version']}"
        for node in graph.get_install_dependencies()
    ]
    assert install_nodes == ["a==2.0", "d==6.0", "b==3.0", "e==6.0"]
