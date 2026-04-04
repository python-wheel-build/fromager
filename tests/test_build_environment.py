import pathlib
import textwrap
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import build_environment
from fromager.commands.build import _get_build_requirements_from_graph
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph, DependencyNode
from fromager.requirements_file import RequirementType


@patch("fromager.resolver.resolve")
def test_missing_dependency_format(
    resolve_dist: Mock,
    tmp_context: WorkContext,
) -> None:
    resolutions = {
        "flit_core": "3.9.0",
        "setuptools": "69.5.1",
    }
    resolve_dist.side_effect = lambda ctx, req, sdist_server_url, req_type: (
        "",
        Version(resolutions[req.name]),
    )

    req = Requirement("setuptools>=40.8.0")
    other_reqs = [
        Requirement("flit_core"),
        req,
    ]
    ex = build_environment.MissingDependency(
        tmp_context, RequirementType.BUILD_BACKEND, req, other_reqs
    )
    s = str(ex)
    # Ensure we report the thing we're actually missing
    assert "Failed to install build-backend dependency setuptools>=40.8.0. " in s
    # Ensure we report what version we expected of that thing
    assert "setuptools>=40.8.0 -> 69.5.1" in s
    # Ensure we report what version we expect of all of the other dependencies
    assert "flit_core -> 3.9.0" in s


def test_missing_dependency_pattern() -> None:
    msg = textwrap.dedent("""
        DEBUG uv 0.8.4
        DEBUG Searching for default Python interpreter in virtual environments
        DEBUG Found `cpython-3.13.5-linux-x86_64-gnu` at `.../.venv/bin/python3` (active virtual environment)
        DEBUG Using Python 3.13.5 environment at: .venv
        DEBUG Acquired lock for `.venv`
        DEBUG At least one requirement is not satisfied: fromager==1.0
        DEBUG Using request timeout of 30s
        DEBUG Solving with installed Python version: 3.13.5
        DEBUG Solving with target Python version: >=3.13.5
        DEBUG Adding direct dependency: fromager>=1.0, <1.0+
        DEBUG Found fresh response for: https://pypi.org/simple/fromager/
        DEBUG Searching for a compatible version of fromager (>=1.0, <1.0+)
        DEBUG No compatible version found for: fromager
        x No solution found when resolving dependencies:
        ╰─▶ Because there is no version of fromager==1.0 and you require fromager==1.0, we can conclude that your requirements are unsatisfiable.
        """)
    match = build_environment._uv_missing_dependency_pattern.search(msg)
    assert match is not None


def test_missing_dependency_pattern_resolution_impossible() -> None:
    msg = textwrap.dedent("""
        DEBUG uv 0.8.4
        DEBUG Searching for default Python interpreter in virtual environments
        DEBUG Found `cpython-3.13.5-linux-x86_64-gnu` at `.../.venv/bin/python3` (active virtual environment)
        DEBUG Using Python 3.13.5 environment at: .venv
        DEBUG Acquired lock for `.venv`
        DEBUG At least one requirement is not satisfied: fromager==2.0
        DEBUG Using request timeout of 30s
        DEBUG Solving with installed Python version: 3.13.5
        DEBUG Solving with target Python version: >=3.13.5
        DEBUG Adding direct dependency: fromager>=1.0, <1.0+
        DEBUG Adding direct dependency: fromager>=2.0, <2.0+
        DEBUG Found fresh response for: https://pypi.org/simple/fromager/
        x No solution found when resolving dependencies:
        ╰─▶ Because you require fromager==1.0 and fromager==2.0, we can conclude that your requirements are unsatisfiable.
    """)
    match = build_environment._uv_missing_dependency_pattern.search(msg)
    assert match is not None


@patch("fromager.build_environment.BuildEnvironment")
def test_prepare_build_environment_from_graph_installs_deps(
    mock_build_env_cls: Mock,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """Verify graph-based build env installs resolved deps without discovery."""
    mock_build_env = Mock()
    mock_build_env.get_distributions.return_value = {}
    mock_build_env_cls.return_value = mock_build_env

    sdist_root_dir = tmp_path / "pkg-1.0" / "pkg-1.0"
    sdist_root_dir.mkdir(parents=True)

    nodes = [
        DependencyNode(canonicalize_name("setuptools"), Version("80.8.0")),
        DependencyNode(canonicalize_name("wheel"), Version("0.46.1")),
    ]

    result = build_environment.prepare_build_environment_from_graph(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        sdist_root_dir=sdist_root_dir,
        build_requirements=nodes,
    )

    assert result is mock_build_env
    mock_build_env.install.assert_called_once()
    installed_reqs = mock_build_env.install.call_args[0][0]
    installed_names = {str(r) for r in installed_reqs}
    assert installed_names == {"setuptools==80.8.0", "wheel==0.46.1"}


@patch("fromager.build_environment.BuildEnvironment")
def test_prepare_build_environment_from_graph_no_deps(
    mock_build_env_cls: Mock,
    tmp_context: WorkContext,
    tmp_path: pathlib.Path,
) -> None:
    """Verify graph-based build env works with no build deps."""
    mock_build_env = Mock()
    mock_build_env.get_distributions.return_value = {}
    mock_build_env_cls.return_value = mock_build_env

    sdist_root_dir = tmp_path / "pkg-1.0" / "pkg-1.0"
    sdist_root_dir.mkdir(parents=True)

    result = build_environment.prepare_build_environment_from_graph(
        ctx=tmp_context,
        req=Requirement("pkg==1.0"),
        sdist_root_dir=sdist_root_dir,
        build_requirements=[],
    )

    assert result is mock_build_env
    mock_build_env.install.assert_not_called()


def test_get_build_requirements_from_graph() -> None:
    """Verify build requirements are extracted from graph nodes."""
    graph = DependencyGraph()
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pkg==1.0"),
        req_version=Version("1.0"),
        download_url="https://example.com/pkg-1.0.tar.gz",
    )
    graph.add_dependency(
        parent_name=canonicalize_name("pkg"),
        parent_version=Version("1.0"),
        req_type=RequirementType.BUILD_SYSTEM,
        req=Requirement("setuptools>=61.2"),
        req_version=Version("80.8.0"),
        download_url="https://example.com/setuptools-80.8.0.tar.gz",
    )

    result = _get_build_requirements_from_graph(graph, "pkg", Version("1.0"))

    assert result is not None
    assert len(result) == 1
    assert result[0].canonicalized_name == canonicalize_name("setuptools")
    assert result[0].version == Version("80.8.0")


def test_get_build_requirements_from_graph_missing_node() -> None:
    """Verify missing node raises KeyError."""
    graph = DependencyGraph()
    with pytest.raises(KeyError, match="nonexistent"):
        _get_build_requirements_from_graph(graph, "nonexistent", Version("1.0"))
