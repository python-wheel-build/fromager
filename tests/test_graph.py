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
        "constraint": None,
        "edges": [{"key": "a==2.0", "req_type": "install", "req": "a==2.0"}],
    },
    "a==2.0": {
        "download_url": "url",
        "pre_built": False,
        "version": "2.0",
        "canonicalized_name": "a",
        "constraint": None,
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
        "constraint": None,
        "edges": [
            {"key": "c==4.0", "req_type": "build-sdist", "req": "c<=4.0"},
        ],
    },
    "c==4.0": {
        "download_url": "url for c",
        "pre_built": False,
        "version": "4.0",
        "canonicalized_name": "c",
        "constraint": None,
        "edges": [],
    },
}


def test_graph_add_dependency() -> None:
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


def test_graph_from_dict() -> None:
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    assert graph._to_dict() == raw_graph


def test_get_install_dependencies() -> None:
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


def test_graph_add_dependency_with_constraint() -> None:
    """Test that constraints are properly stored in dependency nodes."""
    graph = dependency_graph.DependencyGraph()

    # Add top-level dependency with constraint
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("package-a>=1.0"),
        req_version=Version("2.0"),
        download_url="url",
        constraint=Requirement("package-a>=1.0,<3.0"),
    )

    # Verify constraint is stored
    node = graph.nodes["package-a==2.0"]
    assert node.constraint is not None
    assert str(node.constraint) == "package-a<3.0,>=1.0"

    # Add child dependency with its own constraint
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("2.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("package-b>=2.0"),
        req_version=Version("2.5.0"),
        download_url="url-b",
        constraint=Requirement("package-b>=2.0,<3.0"),
    )

    # Verify child constraint is stored
    child_node = graph.nodes["package-b==2.5.0"]
    assert child_node.constraint is not None
    assert str(child_node.constraint) == "package-b<3.0,>=2.0"


def test_graph_constraint_serialization() -> None:
    """Test that constraints survive to_dict/from_dict roundtrip."""
    graph = dependency_graph.DependencyGraph()

    # Add dependencies with various constraints
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("pkg-with-constraint"),
        req_version=Version("1.5.0"),
        download_url="url",
        constraint=Requirement("pkg-with-constraint>=1.0,<2.0"),
    )

    graph.add_dependency(
        parent_name=canonicalize_name("pkg-with-constraint"),
        parent_version=Version("1.5.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("dependency-pkg"),
        req_version=Version("3.0.0"),
        download_url="url-dep",
        constraint=Requirement("dependency-pkg==3.0.0"),
    )

    # Add dependency without constraint
    graph.add_dependency(
        parent_name=canonicalize_name("pkg-with-constraint"),
        parent_version=Version("1.5.0"),
        req_type=requirements_file.RequirementType.BUILD_SYSTEM,
        req=Requirement("build-pkg"),
        req_version=Version("1.0.0"),
        download_url="url-build",
    )

    # Serialize and deserialize
    graph_dict = graph._to_dict()
    restored_graph = dependency_graph.DependencyGraph.from_dict(graph_dict)

    # Verify constraints are preserved
    node1 = restored_graph.nodes["pkg-with-constraint==1.5.0"]
    assert node1.constraint is not None
    assert str(node1.constraint) == "pkg-with-constraint<2.0,>=1.0"

    node2 = restored_graph.nodes["dependency-pkg==3.0.0"]
    assert node2.constraint is not None
    assert str(node2.constraint) == "dependency-pkg==3.0.0"

    # Verify None constraint is preserved
    node3 = restored_graph.nodes["build-pkg==1.0.0"]
    assert node3.constraint is None


def test_graph_duplicate_node_constraint_behavior() -> None:
    """Test behavior when same package is added with different constraints.

    When a node with the same key (name==version) is added multiple times,
    the first node is reused, including its constraint value.
    """
    graph = dependency_graph.DependencyGraph()

    # Add package with first constraint
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("shared-pkg>=1.0"),
        req_version=Version("2.0"),
        download_url="url1",
        constraint=Requirement("shared-pkg>=1.0,<3.0"),
    )

    # Add another toplevel
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("other-pkg"),
        req_version=Version("1.0"),
        download_url="url2",
    )

    # Add same package as dependency with different constraint
    graph.add_dependency(
        parent_name=canonicalize_name("other-pkg"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("shared-pkg>=2.0"),
        req_version=Version("2.0"),
        download_url="url1",
        constraint=Requirement("shared-pkg>=2.0,<4.0"),  # Different constraint
    )

    # The first constraint should be retained (existing node is reused)
    node = graph.nodes["shared-pkg==2.0"]
    assert node.constraint is not None
    assert str(node.constraint) == "shared-pkg<3.0,>=1.0"

    # Verify both parents exist
    assert len(node.parents) == 2


def test_graph_constraint_in_to_dict() -> None:
    """Test that to_dict() includes constraint information."""
    graph = dependency_graph.DependencyGraph()

    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("test-pkg"),
        req_version=Version("1.0.0"),
        download_url="https://example.com/test-pkg.tar.gz",
        constraint=Requirement("test-pkg>=1.0,<2.0"),
    )

    graph_dict = graph._to_dict()

    # Verify constraint is in the serialized format (as string in JSON)
    assert "test-pkg==1.0.0" in graph_dict
    assert graph_dict["test-pkg==1.0.0"]["constraint"] == "test-pkg<2.0,>=1.0"


def test_cycles_get_install_dependencies() -> None:
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    # create cycle: a depends on d and d depends on a
    graph.add_dependency(
        parent_name=canonicalize_name("a"),
        parent_version=Version("2.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("d>=4.0"),
        req_version=Version("6.0"),
        download_url="url for d",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("d"),
        parent_version=Version("6.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("a<=2.0"),
        req_version=Version("2.0"),
        download_url="url for a",
    )

    # add another duplicate toplevel
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("a<=2.0"),
        req_version=Version("2.0"),
        download_url="url for a",
    )

    install_nodes = [
        f"{node.to_dict()['canonicalized_name']}=={node.to_dict()['version']}"
        for node in graph.get_install_dependencies()
    ]
    assert install_nodes == ["a==2.0", "d==6.0"]
