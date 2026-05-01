"""Tests for the graph suggest-collection command and its helper functions."""

import json
import pathlib
import re

import pytest
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.__main__ import main as fromager
from fromager.commands.graph import (
    _analyze_suggestions,
    extract_collection_name,
    get_dependency_closure,
    get_package_names,
)
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType


def _extract_json_from_output(output: str) -> str:
    """Extract JSON array from output that may contain leading log lines."""
    json_match = re.search(r"\[.*\]", output, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return "[]"


def _build_graph(
    toplevel: dict[str, str],
    dependencies: dict[str, list[tuple[str, str, str]]],
) -> DependencyGraph:
    """Build a synthetic DependencyGraph for testing.

    Args:
        toplevel: Mapping of package name to version for top-level packages.
        dependencies: Mapping of ``"name==version"`` to a list of
            ``(dep_name, dep_version, req_type)`` tuples.

    Returns:
        A populated DependencyGraph.
    """
    graph = DependencyGraph()
    for name, version in toplevel.items():
        graph.add_dependency(
            parent_name=None,
            parent_version=None,
            req_type=RequirementType.TOP_LEVEL,
            req=Requirement(name),
            req_version=Version(version),
        )

    for parent_key, deps in dependencies.items():
        pname, _, pver = parent_key.partition("==")
        for dep_name, dep_version, req_type_str in deps:
            graph.add_dependency(
                parent_name=canonicalize_name(pname),
                parent_version=Version(pver),
                req_type=RequirementType(req_type_str),
                req=Requirement(f"{dep_name}>={dep_version}"),
                req_version=Version(dep_version),
            )
    return graph


def _write_graph(graph: DependencyGraph, path: pathlib.Path) -> None:
    """Serialize a DependencyGraph to a JSON file."""
    with open(path, "w") as f:
        graph.serialize(f)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestGetDependencyClosure:
    """Tests for get_dependency_closure."""

    def test_single_package_no_deps(self) -> None:
        """A top-level package with no dependencies has a closure of itself."""
        graph = _build_graph({"alpha": "1.0"}, {})
        node = graph.nodes["alpha==1.0"]
        closure = get_dependency_closure(node)
        assert closure == {canonicalize_name("alpha")}

    def test_transitive_install_deps(self) -> None:
        """Closure includes transitive install dependencies."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {
                "alpha==1.0": [("bravo", "2.0", "install")],
                "bravo==2.0": [("charlie", "3.0", "install")],
            },
        )
        node = graph.nodes["alpha==1.0"]
        closure = get_dependency_closure(node)
        assert closure == {
            canonicalize_name("alpha"),
            canonicalize_name("bravo"),
            canonicalize_name("charlie"),
        }

    def test_includes_build_deps(self) -> None:
        """Default closure includes build-system dependencies."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {
                "alpha==1.0": [
                    ("bravo", "2.0", "install"),
                    ("setuptools", "70.0", "build-system"),
                ],
            },
        )
        node = graph.nodes["alpha==1.0"]
        closure = get_dependency_closure(node)
        assert canonicalize_name("setuptools") in closure
        assert canonicalize_name("bravo") in closure

    def test_cycle_does_not_hang(self) -> None:
        """Circular dependencies terminate without hanging."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {
                "alpha==1.0": [("bravo", "1.0", "install")],
                "bravo==1.0": [("alpha", "1.0", "install")],
            },
        )
        node = graph.nodes["alpha==1.0"]
        closure = get_dependency_closure(node)
        assert closure == {
            canonicalize_name("alpha"),
            canonicalize_name("bravo"),
        }

    def test_diamond_dependency(self) -> None:
        """Diamond-shaped deps are counted once."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {
                "alpha==1.0": [
                    ("bravo", "1.0", "install"),
                    ("charlie", "1.0", "install"),
                ],
                "bravo==1.0": [("delta", "1.0", "install")],
                "charlie==1.0": [("delta", "1.0", "install")],
            },
        )
        node = graph.nodes["alpha==1.0"]
        closure = get_dependency_closure(node)
        assert len(closure) == 4
        assert canonicalize_name("delta") in closure


class TestGetPackageNames:
    """Tests for get_package_names."""

    def test_excludes_root(self) -> None:
        """ROOT node is never in the returned set."""
        graph = _build_graph({"alpha": "1.0"}, {})
        names = get_package_names(graph)
        assert "" not in names
        assert canonicalize_name("alpha") in names

    def test_includes_all_nodes(self) -> None:
        """All non-root nodes contribute their canonical name."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {"alpha==1.0": [("bravo", "2.0", "install")]},
        )
        names = get_package_names(graph)
        assert names == {
            canonicalize_name("alpha"),
            canonicalize_name("bravo"),
        }

    def test_empty_graph(self) -> None:
        """An empty graph (only ROOT) returns an empty set."""
        graph = DependencyGraph()
        names = get_package_names(graph)
        assert names == set()


class TestExtractCollectionName:
    """Tests for extract_collection_name."""

    def test_simple_filename(self) -> None:
        assert extract_collection_name("notebook.json") == "notebook"

    def test_preserves_full_stem(self) -> None:
        assert extract_collection_name("notebook-graph.json") == "notebook-graph"

    def test_preserves_hyphens(self) -> None:
        assert extract_collection_name("rhai-innovation.json") == "rhai-innovation"

    def test_full_path(self) -> None:
        assert extract_collection_name("/tmp/graphs/notebook.json") == "notebook"

    def test_stem_only(self) -> None:
        assert extract_collection_name("my-collection.json") == "my-collection"


# ---------------------------------------------------------------------------
# CLI integration tests for suggest-collection
# ---------------------------------------------------------------------------


class TestSuggestCollectionCLI:
    """Integration tests for ``fromager graph suggest-collection``."""

    @pytest.fixture()
    def graph_dir(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a temporary directory with onboarding and collection graphs."""
        # Onboarding graph: two top-level packages
        #   pkg-x depends on numpy, pandas
        #   pkg-y depends on numpy, torch
        onboard = _build_graph(
            {"pkg-x": "1.0", "pkg-y": "1.0"},
            {
                "pkg-x==1.0": [
                    ("numpy", "1.26", "install"),
                    ("pandas", "2.0", "install"),
                ],
                "pkg-y==1.0": [
                    ("numpy", "1.26", "install"),
                    ("torch", "2.0", "install"),
                ],
            },
        )
        _write_graph(onboard, tmp_path / "onboarding.json")

        # Collection "data-science": has numpy, pandas, scipy
        ds = _build_graph(
            {"numpy": "1.26", "pandas": "2.0", "scipy": "1.12"},
            {},
        )
        _write_graph(ds, tmp_path / "data-science.json")

        # Collection "ml": has numpy, torch, triton
        ml = _build_graph(
            {"numpy": "1.26", "torch": "2.0", "triton": "3.0"},
            {},
        )
        _write_graph(ml, tmp_path / "ml.json")

        return tmp_path

    def test_table_output(
        self,
        cli_runner: CliRunner,
        graph_dir: pathlib.Path,
    ) -> None:
        """Table output contains expected package names and collection fits."""
        result = cli_runner.invoke(
            fromager,
            [
                "graph",
                "suggest-collection",
                str(graph_dir / "onboarding.json"),
                str(graph_dir / "data-science.json"),
                str(graph_dir / "ml.json"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "pkg-x" in result.output
        assert "pkg-y" in result.output
        assert "data-science" in result.output
        assert "ml" in result.output

    def test_json_output(
        self,
        cli_runner: CliRunner,
        graph_dir: pathlib.Path,
    ) -> None:
        """JSON output is parseable and contains expected fields."""
        result = cli_runner.invoke(
            fromager,
            [
                "graph",
                "suggest-collection",
                "--format",
                "json",
                str(graph_dir / "onboarding.json"),
                str(graph_dir / "data-science.json"),
                str(graph_dir / "ml.json"),
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(_extract_json_from_output(result.output))
        assert isinstance(data, list)
        assert len(data) == 2

        packages = {r["package"] for r in data}
        assert packages == {"pkg-x", "pkg-y"}

        for entry in data:
            assert "best_fit" in entry
            assert "total_dependencies" in entry
            assert "coverage_percentage" in entry
            assert "all_collections" in entry
            assert len(entry["all_collections"]) == 2

    def test_best_fit_ranking(
        self,
        cli_runner: CliRunner,
        graph_dir: pathlib.Path,
    ) -> None:
        """pkg-x should prefer data-science, pkg-y should prefer ml."""
        result = cli_runner.invoke(
            fromager,
            [
                "graph",
                "suggest-collection",
                "--format",
                "json",
                str(graph_dir / "onboarding.json"),
                str(graph_dir / "data-science.json"),
                str(graph_dir / "ml.json"),
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(_extract_json_from_output(result.output))
        by_pkg = {r["package"]: r for r in data}

        assert by_pkg["pkg-x"]["best_fit"] == "data-science"
        assert by_pkg["pkg-y"]["best_fit"] == "ml"

    def test_empty_onboarding_graph(
        self,
        cli_runner: CliRunner,
        graph_dir: pathlib.Path,
    ) -> None:
        """Empty onboarding graph warns on stderr and outputs empty results."""
        empty = DependencyGraph()
        _write_graph(empty, graph_dir / "empty.json")

        result = cli_runner.invoke(
            fromager,
            [
                "graph",
                "suggest-collection",
                "--format",
                "json",
                str(graph_dir / "empty.json"),
                str(graph_dir / "data-science.json"),
            ],
        )
        assert result.exit_code == 0
        assert "No top-level packages" in result.output
        data = json.loads(_extract_json_from_output(result.output))
        assert data == []

    def test_no_collection_graphs_fails(
        self,
        cli_runner: CliRunner,
        graph_dir: pathlib.Path,
    ) -> None:
        """Missing collection-graphs argument causes a usage error."""
        result = cli_runner.invoke(
            fromager,
            [
                "graph",
                "suggest-collection",
                str(graph_dir / "onboarding.json"),
            ],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Unit tests for _analyze_suggestions
# ---------------------------------------------------------------------------


class TestAnalyzeSuggestions:
    """Tests for the core scoring logic in _analyze_suggestions."""

    def test_scores_single_package_against_two_collections(self) -> None:
        """Best-fit collection has fewest new packages required."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {
                "alpha==1.0": [
                    ("numpy", "1.26", "install"),
                    ("pandas", "2.0", "install"),
                ],
            },
        )
        toplevel = [graph.nodes["alpha==1.0"]]
        # Both collections include alpha itself; "ds" covers all three deps.
        collection_packages = {
            "ds": {
                canonicalize_name("alpha"),
                canonicalize_name("numpy"),
                canonicalize_name("pandas"),
            },
            "ml": {canonicalize_name("alpha"), canonicalize_name("numpy")},
        }
        results = _analyze_suggestions(toplevel, collection_packages)

        assert len(results) == 1
        entry = results[0]
        assert entry["best_fit"] == "ds"
        assert entry["new_packages"] == 0
        assert entry["existing_packages"] == 3
        assert entry["coverage_percentage"] == 100.0
        assert len(entry["all_collections"]) == 2

    def test_version_difference_does_not_affect_fit(self) -> None:
        """A package at a different version still counts as existing in the collection."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {"alpha==1.0": [("numpy", "2.0", "install")]},
        )
        toplevel = [graph.nodes["alpha==1.0"]]
        # Collection has both packages, but numpy at an older version.
        collection_packages = {
            "ds": {canonicalize_name("alpha"), canonicalize_name("numpy")},
        }
        results = _analyze_suggestions(toplevel, collection_packages)

        # numpy at version 2.0 (onboarding) vs 1.26 (collection) should still match.
        assert results[0]["new_packages"] == 0
        assert results[0]["existing_packages"] == 2
        assert results[0]["coverage_percentage"] == 100.0

    def test_result_sorted_by_package_name(self) -> None:
        """Results are returned alphabetically by package name."""
        graph = _build_graph({"zebra": "1.0", "alpha": "1.0"}, {})
        toplevel = [graph.nodes["zebra==1.0"], graph.nodes["alpha==1.0"]]
        results = _analyze_suggestions(toplevel, {"empty": set()})
        assert [r["package"] for r in results] == ["alpha", "zebra"]

    def test_all_collections_ranked_ascending_new_packages(self) -> None:
        """all_collections list is ordered fewest-new-packages first."""
        graph = _build_graph(
            {"alpha": "1.0"},
            {"alpha==1.0": [("numpy", "1.0", "install"), ("pandas", "1.0", "install")]},
        )
        toplevel = [graph.nodes["alpha==1.0"]]
        collection_packages = {
            "best": {canonicalize_name("numpy"), canonicalize_name("pandas")},
            "mid": {canonicalize_name("numpy")},
            "worst": set(),
        }
        results = _analyze_suggestions(toplevel, collection_packages)
        ranked = [c["collection"] for c in results[0]["all_collections"]]
        new_pkg_counts = [c["new_packages"] for c in results[0]["all_collections"]]
        assert new_pkg_counts == sorted(new_pkg_counts), (
            f"all_collections not sorted by new_packages: {ranked}"
        )
