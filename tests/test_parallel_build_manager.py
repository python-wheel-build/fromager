from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import context, dependency_graph, requirements_file
from fromager.commands.build import ParallelBuildManager


def create_test_graph():
    """Create a test dependency graph with various dependency scenarios.

    Graph structure:
    - app_main: Top-level app (depends on lib_shared for install, tool_build for build)
    - lib_shared: Shared library (depends on util_base for install, no build deps)
    - util_base: Base utility (no dependencies - leaf node)
    - tool_build: Build tool (depends on util_base for build and install)
    - plugin_extra: Plugin (depends on lib_shared for install, tool_build for build)
    - helper_internal: Internal helper (only used by tool_build, not top-level)

    Expected build order: util_base → helper_internal → tool_build → lib_shared → (app_main, plugin_extra)
    """
    graph = dependency_graph.DependencyGraph()

    # Add top-level dependencies (directly requested by user)
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("app_main==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/app_main-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("lib_shared==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/lib_shared-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=requirements_file.RequirementType.TOP_LEVEL,
        req=Requirement("plugin_extra==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/plugin_extra-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("app_main"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.BUILD_SYSTEM,
        req=Requirement("tool_build==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/tool_build-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("app_main"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("lib_shared==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/lib_shared-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("lib_shared"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("util_base==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/util_base-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("plugin_extra"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.BUILD_BACKEND,
        req=Requirement("tool_build==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/tool_build-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("plugin_extra"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("lib_shared==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/lib_shared-1.0.tar.gz",
    )

    # tool_build build dependencies (not top-level, only used by others)
    graph.add_dependency(
        parent_name=canonicalize_name("tool_build"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.BUILD_SYSTEM,
        req=Requirement("util_base==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/util_base-1.0.tar.gz",
    )

    graph.add_dependency(
        parent_name=canonicalize_name("tool_build"),
        parent_version=Version("1.0"),
        req_type=requirements_file.RequirementType.INSTALL,
        req=Requirement("helper_internal==1.0"),
        req_version=Version("1.0"),
        download_url="http://example.com/helper_internal-1.0.tar.gz",
    )

    # util_base has no dependencies (leaf node)
    # helper_internal has no dependencies (leaf node, not top-level)

    return graph


@pytest.fixture
def mock_context():
    """Create a mock WorkContext for testing."""
    ctx = Mock(spec=context.WorkContext)
    ctx.settings = Mock()

    def mock_package_build_info(name):
        mock_pbi = Mock()
        mock_pbi.exclusive_build = False
        return mock_pbi

    ctx.settings.package_build_info = mock_package_build_info
    return ctx


@pytest.fixture
def test_graph():
    """Provide the test dependency graph."""
    return create_test_graph()


@pytest.fixture
def build_manager(mock_context, test_graph):
    """Create a ParallelBuildManager instance for testing."""
    return ParallelBuildManager(mock_context, test_graph)


class TestParallelBuildManager:
    """Test suite for ParallelBuildManager class."""

    def test_initialization(self, build_manager, test_graph):
        """Test that the manager initializes correctly."""
        assert build_manager.wkctx is not None
        assert build_manager.graph == test_graph
        assert len(build_manager.built_node_keys) == 0
        assert len(build_manager._remaining_nodes) == 6  # 6 non-root nodes
        assert build_manager.have_remaining_nodes()

    def test_have_remaining_nodes_initially_true(self, build_manager):
        """Test that initially there are remaining nodes."""
        assert build_manager.have_remaining_nodes()

    def test_have_remaining_nodes_false_when_all_built(self, build_manager, test_graph):
        """Test that have_remaining_nodes returns False when all nodes are built."""
        # Mark all nodes as built
        for node in test_graph.nodes.values():
            if node.key != dependency_graph.ROOT:
                build_manager.mark_node_built(node)

        assert not build_manager.have_remaining_nodes()

    def test_mark_node_built(self, build_manager, test_graph):
        """Test marking nodes as built."""
        util_base = test_graph.nodes["util-base==1.0"]

        assert not build_manager.is_node_built(util_base)
        assert util_base.key not in build_manager.built_node_keys
        assert util_base in build_manager._remaining_nodes

        build_manager.mark_node_built(util_base)

        # Verify node is now marked as built
        assert build_manager.is_node_built(util_base)
        assert util_base.key in build_manager.built_node_keys
        assert util_base not in build_manager._remaining_nodes

    def test_nodes_with_no_dependencies_buildable_first(self, build_manager):
        """Test that leaf nodes (no dependencies) are buildable first."""
        buildable_nodes = build_manager.get_nodes_ready_to_build()

        buildable_names = {node.canonicalized_name for node in buildable_nodes}
        assert (
            len(buildable_nodes) == 3
        )  # util-base, helper-internal, and lib-shared (no build deps)
        assert "util-base" in buildable_names
        assert "helper-internal" in buildable_names
        assert "lib-shared" in buildable_names

    def test_node_with_build_dependencies(self, build_manager, test_graph):
        """Test that tool_build becomes buildable after its dependencies are built."""
        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}
        assert "util-base" in buildable_names
        assert "helper-internal" in buildable_names
        assert "tool-build" not in buildable_names

        util_base = test_graph.nodes["util-base==1.0"]
        helper_internal = test_graph.nodes["helper-internal==1.0"]
        build_manager.mark_node_built(util_base)
        build_manager.mark_node_built(helper_internal)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}
        assert "tool-build" in buildable_names

    def test_transitive_dependencies(self, build_manager, test_graph):
        """Test that transitive dependencies are handled correctly.

        app_main depends on tool_build for build, and tool_build depends on helper_internal for install.
        So app_main should only be buildable after util_base, helper_internal, and tool_build are built.
        """
        util_base = test_graph.nodes["util-base==1.0"]
        build_manager.mark_node_built(util_base)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert "app-main" not in buildable_names
        assert (
            "helper-internal" in buildable_names
        )  # helper_internal should still be buildable

        helper_internal = test_graph.nodes["helper-internal==1.0"]
        build_manager.mark_node_built(helper_internal)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert "tool-build" in buildable_names
        assert "app-main" not in buildable_names

        tool_build = test_graph.nodes["tool-build==1.0"]
        build_manager.mark_node_built(tool_build)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert "lib-shared" in buildable_names

    def test_multiple_build_dependencies(self, build_manager, test_graph):
        """Test that app_main waits for all its dependencies."""
        # app_main depends on tool_build for build and lib_shared for install
        # tool_build depends on util_base and helper_internal
        # lib_shared depends on util_base

        util_base = test_graph.nodes["util-base==1.0"]
        build_manager.mark_node_built(util_base)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert "app-main" not in buildable_names

        helper_internal = test_graph.nodes["helper-internal==1.0"]
        build_manager.mark_node_built(helper_internal)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}
        assert "tool-build" in buildable_names

        tool_build = test_graph.nodes["tool-build==1.0"]
        build_manager.mark_node_built(tool_build)

        lib_shared = test_graph.nodes["lib-shared==1.0"]
        build_manager.mark_node_built(lib_shared)

        buildable_nodes = build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert "app-main" in buildable_names

    def test_circular_dependency_detection(self, build_manager, test_graph):
        """Test that circular dependencies are detected."""
        # Create a scenario where no nodes can be built but some remain
        # Mark all nodes as remaining but create impossible conditions

        # Remove all leaf nodes from remaining nodes but don't mark them as built
        # This simulates a circular dependency scenario where no nodes can be built
        build_manager._remaining_nodes = [
            node
            for node in build_manager._remaining_nodes
            if node.canonicalized_name
            not in ["util-base", "helper-internal", "lib-shared"]
        ]

        with pytest.raises(ValueError, match="Circular dependency detected"):
            build_manager.get_nodes_ready_to_build()

    @patch("fromager.commands.build.logger")
    def test_logging_messages(self, mock_logger, build_manager, test_graph):
        """Test that appropriate logging messages are generated."""
        build_manager.get_nodes_ready_to_build()

        mock_logger.info.assert_called()
        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("ready to build" in msg for msg in log_calls)

        util_base = test_graph.nodes["util-base==1.0"]
        build_manager.mark_node_built(util_base)
        mock_logger.reset_mock()

        build_manager.get_nodes_ready_to_build()

        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("waiting for" in msg for msg in log_calls)


class TestExclusiveBuildHandling:
    """Test suite specifically for exclusive build handling."""

    def create_exclusive_build_graph(self):
        """Create a graph where some nodes require exclusive builds."""
        graph = dependency_graph.DependencyGraph()

        for name in ["normal_a", "normal_b", "exclusive_c"]:
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=requirements_file.RequirementType.INSTALL,
                req=Requirement(f"{name}==1.0"),
                req_version=Version("1.0"),
                download_url=f"http://example.com/{name}-1.0.tar.gz",
            )

        return graph

    @pytest.fixture
    def exclusive_build_manager(self, mock_context):
        """Create a manager with exclusive build settings."""
        graph = self.create_exclusive_build_graph()

        def mock_package_build_info(name):
            mock_pbi = Mock()
            mock_pbi.exclusive_build = name == "exclusive-c"
            return mock_pbi

        mock_context.settings.package_build_info = mock_package_build_info

        return ParallelBuildManager(mock_context, graph)

    def test_exclusive_build_isolation(self, exclusive_build_manager):
        """Test that exclusive build nodes are not mixed with other nodes."""
        buildable_nodes = exclusive_build_manager.get_nodes_ready_to_build()

        assert len(buildable_nodes) == 1
        assert buildable_nodes[0].canonicalized_name == "exclusive-c"

    def test_normal_nodes_built_together_when_no_exclusive(
        self, exclusive_build_manager
    ):
        """Test that normal nodes can be built together when no exclusive nodes are ready."""
        exclusive_node = None
        for node in exclusive_build_manager._remaining_nodes:
            if node.canonicalized_name == "exclusive-c":
                exclusive_node = node
                break

        assert exclusive_node is not None
        exclusive_build_manager.mark_node_built(exclusive_node)

        buildable_nodes = exclusive_build_manager.get_nodes_ready_to_build()
        buildable_names = {node.canonicalized_name for node in buildable_nodes}

        assert len(buildable_nodes) == 2
        assert "normal-a" in buildable_names
        assert "normal-b" in buildable_names
        assert "exclusive-c" not in buildable_names

    def test_multiple_exclusive_nodes_only_first_selected(self, mock_context):
        """Test that when multiple exclusive nodes are ready, only the first is selected."""
        graph = dependency_graph.DependencyGraph()

        for name in ["exclusive_a", "exclusive_b", "normal_c"]:
            graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=requirements_file.RequirementType.INSTALL,
                req=Requirement(f"{name}==1.0"),
                req_version=Version("1.0"),
                download_url=f"http://example.com/{name}-1.0.tar.gz",
            )

        def mock_package_build_info(name):
            mock_pbi = Mock()
            mock_pbi.exclusive_build = name.startswith("exclusive-")
            return mock_pbi

        mock_context.settings.package_build_info = mock_package_build_info
        manager = ParallelBuildManager(mock_context, graph)

        buildable_nodes = manager.get_nodes_ready_to_build()

        assert len(buildable_nodes) == 1
        assert buildable_nodes[0].canonicalized_name.startswith("exclusive-")

    @patch("fromager.commands.build.logger")
    def test_exclusive_build_logging(self, mock_logger, exclusive_build_manager):
        """Test that exclusive build scenarios are logged appropriately."""
        exclusive_build_manager.get_nodes_ready_to_build()

        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        exclusive_log_found = any(
            "requires exclusive build" in msg for msg in log_calls
        )
        assert exclusive_log_found
