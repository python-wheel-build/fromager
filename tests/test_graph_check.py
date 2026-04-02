import json
import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager
from fromager.commands.graph import (
    _check_acyclicity,
    _check_well_formed,
    _classify_conflicts,
)
from fromager.dependency_graph import DependencyGraph


def _make_graph_dict(
    packages: dict[str, dict],
) -> dict[str, dict]:
    """Build a minimal graph JSON dict from a simplified spec.

    packages maps "name==version" to {"edges": [{"key": ..., "req_type": ..., "req": ...}]}
    The ROOT node is added automatically with toplevel edges to all packages
    that aren't edge targets.
    """
    all_targets = set()
    for info in packages.values():
        for edge in info.get("edges", []):
            all_targets.add(edge["key"])

    roots = [k for k in packages if k not in all_targets]

    result: dict[str, dict] = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": k, "req_type": "toplevel", "req": k} for k in roots],
        }
    }
    for key, info in packages.items():
        name, version = key.split("==")
        result[key] = {
            "download_url": "",
            "pre_built": False,
            "version": version,
            "canonicalized_name": name,
            "edges": info.get("edges", []),
        }
    return result


def _write_graph(tmp_path: pathlib.Path, graph_dict: dict) -> pathlib.Path:
    """Write a graph dict to a JSON file and return the path."""
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph_dict))
    return p


# ---------------------------------------------------------------------------
# Unit tests for _check_well_formed
# ---------------------------------------------------------------------------


class TestCheckWellFormed:
    """Tests for _check_well_formed on raw graph dicts."""

    def test_clean_graph(self) -> None:
        """No issues when all edge targets exist."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==2.0", "req_type": "install", "req": "b>=1.0"}]
                },
                "b==2.0": {"edges": []},
            }
        )
        assert _check_well_formed(d) == []

    def test_dangling_edge(self) -> None:
        """Detects edges pointing to missing nodes."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "missing==1.0", "req_type": "install", "req": "missing"}
        )
        issues = _check_well_formed(d)
        assert len(issues) == 1
        assert "missing==1.0" in issues[0]
        assert "DANGLING EDGE" in issues[0]

    def test_deduplicates_by_target(self) -> None:
        """Multiple edges to same missing target produce one issue."""
        d = _make_graph_dict({"a==1.0": {"edges": []}, "b==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "missing==1.0", "req_type": "install", "req": "missing"}
        )
        d["b==1.0"]["edges"].append(
            {"key": "missing==1.0", "req_type": "build-system", "req": "missing"}
        )
        issues = _check_well_formed(d)
        assert len(issues) == 1
        assert "2 edge(s)" in issues[0]


# ---------------------------------------------------------------------------
# Unit tests for _check_acyclicity (operates on raw dict)
# ---------------------------------------------------------------------------


class TestCheckAcyclicity:
    """Tests for _check_acyclicity on raw graph dicts."""

    def test_clean_graph(self) -> None:
        """No issues for acyclic graph."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==2.0", "req_type": "install", "req": "b>=1.0"}]
                },
                "b==2.0": {"edges": []},
            }
        )
        cycles, self_loops = _check_acyclicity(d)
        assert cycles == []
        assert self_loops == []

    def test_self_loop(self) -> None:
        """Self-loops are returned as warnings, not cycles."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "a==1.0", "req_type": "install", "req": "a[extras]"}
        )
        cycles, self_loops = _check_acyclicity(d)
        assert cycles == []
        assert len(self_loops) == 1
        assert "SELF-LOOP" in self_loops[0]
        assert "a==1.0" in self_loops[0]

    def test_cycle(self) -> None:
        """Detects a two-node cycle in raw dict."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==1.0", "req_type": "install", "req": "b"}]
                },
                "b==1.0": {
                    "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}]
                },
            }
        )
        cycles, self_loops = _check_acyclicity(d)
        assert any("CYCLE" in i for i in cycles)
        assert self_loops == []

    def test_dangling_edge_skipped(self) -> None:
        """Dangling edges don't crash cycle detection."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "missing==1.0", "req_type": "install", "req": "missing"}
        )
        # Should not raise
        cycles, _self_loops = _check_acyclicity(d)
        assert cycles == []

    def test_three_node_cycle(self) -> None:
        """Detects a three-node cycle: a -> b -> c -> a."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==1.0", "req_type": "install", "req": "b"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c"}]
                },
                "c==1.0": {
                    "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}]
                },
            }
        )
        cycles, self_loops = _check_acyclicity(d)
        assert len(cycles) == 1
        assert "a==1.0" in cycles[0]
        assert "b==1.0" in cycles[0]
        assert "c==1.0" in cycles[0]
        assert self_loops == []


# ---------------------------------------------------------------------------
# Unit tests for _classify_conflicts
# ---------------------------------------------------------------------------


class TestClassifyConflicts:
    """Tests for _classify_conflicts on DependencyGraph objects."""

    def test_no_conflicts(self) -> None:
        """No entries when each package has one version."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==2.0", "req_type": "install", "req": "b>=1.0"}]
                },
                "b==2.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        assert _classify_conflicts(graph) == []

    def test_collapsible_conflict(self) -> None:
        """Detects collapsible when one version satisfies all consumers."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        entries = _classify_conflicts(graph)
        assert len(entries) == 1
        assert entries[0]["name"] == "c"
        assert entries[0]["pin"] == "2.0"  # highest feasible version preferred

    def test_collapsible_asymmetric(self) -> None:
        """When only one specific version is the valid pin."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "b==1.0": {
                    "edges": [
                        {"key": "c==2.0", "req_type": "install", "req": "c>=2.0,<3.0"}
                    ]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        entries = _classify_conflicts(graph)
        assert len(entries) == 1
        # Only 2.0 satisfies both >=1.0 and >=2.0,<3.0
        assert entries[0]["pin"] == "2.0"

    def test_required_conflict(self) -> None:
        """Detects required when no single version satisfies all consumers."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c<2.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=2.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        entries = _classify_conflicts(graph)
        assert len(entries) == 1
        assert entries[0]["name"] == "c"
        assert entries[0]["pin"] is None

    def test_build_system_only_invisible(self) -> None:
        """Build-system multi-version packages are not reported.

        _classify_conflicts uses get_install_dependency_versions(), so
        build-system-only version splits (e.g. setuptools 69.0 vs 70.0)
        are intentionally excluded.
        """
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [
                        {
                            "key": "setuptools==69.0",
                            "req_type": "build-system",
                            "req": "setuptools",
                        }
                    ]
                },
                "b==1.0": {
                    "edges": [
                        {
                            "key": "setuptools==70.0",
                            "req_type": "build-system",
                            "req": "setuptools",
                        }
                    ]
                },
                "setuptools==69.0": {"edges": []},
                "setuptools==70.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        entries = _classify_conflicts(graph)
        assert entries == []

    def test_same_parent_two_versions(self) -> None:
        """Parent with edges to two versions of the same dependency."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [
                        {"key": "c==1.0", "req_type": "install", "req": "c>=1.0"},
                        {"key": "c==2.0", "req_type": "install", "req": "c>=1.0"},
                    ]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph = DependencyGraph.from_dict(d)
        entries = _classify_conflicts(graph)
        assert len(entries) == 1
        assert entries[0]["name"] == "c"
        # Both versions satisfy >=1.0, so it should be collapsible
        assert entries[0]["pin"] is not None


# ---------------------------------------------------------------------------
# CLI integration tests via CliRunner
# ---------------------------------------------------------------------------


class TestCheckCLI:
    """Integration tests for `fromager graph check`."""

    def test_clean_graph_passes(
        self, cli_runner: CliRunner, e2e_path: pathlib.Path
    ) -> None:
        """build-parallel graph should pass all checks."""
        graph_json = e2e_path / "build-parallel" / "graph.json"
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_json)])
        assert result.exit_code == 0
        assert "[PASS] Well-formed" in result.output
        assert "[PASS] Acyclic" in result.output
        assert "[PASS] Version-unique" in result.output
        assert "All checks pass" in result.output

    def test_clean_graph_json(
        self, cli_runner: CliRunner, e2e_path: pathlib.Path
    ) -> None:
        """JSON output for clean graph has correct structure."""
        graph_json = e2e_path / "build-parallel" / "graph.json"
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--json", str(graph_json)]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["well_formed"]["pass"] is True
        assert data["acyclic"]["pass"] is True
        assert data["version_unique"]["pass"] is True
        assert data["conflict_analysis"] == []

    def test_clean_graph_constraints(
        self, cli_runner: CliRunner, e2e_path: pathlib.Path
    ) -> None:
        """Constraints output for clean graph is empty (nothing to pin)."""
        graph_json = e2e_path / "build-parallel" / "graph.json"
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--constraints", str(graph_json)]
        )
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_conflict_graph_fails(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Graph with conflicts exits non-zero."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c<2.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=2.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_file)])
        assert result.exit_code != 0
        assert "[FAIL] Version-unique" in result.output

    def test_conflict_json_structure(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """JSON output for conflict graph has conflict_analysis entries."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--json", str(graph_file)]
        )
        data = json.loads(result.output)
        assert data["version_unique"]["pass"] is False
        assert data["version_unique"]["n_conflicts"] == 1
        assert len(data["conflict_analysis"]) == 1
        assert data["conflict_analysis"][0]["name"] == "c"
        assert data["conflict_analysis"][0]["pin"] is not None

    def test_constraints_collapsible_exits_zero(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Constraints mode with collapsible-only conflict exits 0."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=1.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--constraints", str(graph_file)]
        )
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("c==")

    def test_constraints_required_exits_nonzero(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Constraints mode with required conflict exits non-zero."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "c==1.0", "req_type": "install", "req": "c<2.0"}]
                },
                "b==1.0": {
                    "edges": [{"key": "c==2.0", "req_type": "install", "req": "c>=2.0"}]
                },
                "c==1.0": {"edges": []},
                "c==2.0": {"edges": []},
            }
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--constraints", str(graph_file)]
        )
        assert result.exit_code != 0
        # No output — nothing collapsible to suggest
        assert result.output.strip() == ""

    def test_json_and_constraints_mutually_exclusive(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Passing both --json and --constraints is an error."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--json", "--constraints", str(graph_file)]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_dangling_edge_fails(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Graph with dangling edges exits non-zero and reports issue."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "missing==1.0", "req_type": "install", "req": "missing"}
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_file)])
        assert result.exit_code != 0
        assert "[FAIL] Well-formed" in result.output
        assert "dangling edge" in result.output.lower()

    def test_self_loop_warning(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Self-loop is a warning, not a failure — exits 0."""
        d = _make_graph_dict({"a==1.0": {"edges": []}})
        d["a==1.0"]["edges"].append(
            {"key": "a==1.0", "req_type": "install", "req": "a[extras]"}
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_file)])
        assert result.exit_code == 0
        assert "[PASS] Acyclic" in result.output
        assert "self-loop warning" in result.output.lower()
        assert "SELF-LOOP" in result.output

    def test_cycle_detected(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """Cycle in raw graph is detected and reported."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==1.0", "req_type": "install", "req": "b"}]
                },
                "b==1.0": {
                    "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}]
                },
            }
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_file)])
        assert result.exit_code != 0
        assert "CYCLE" in result.output

    def test_json_cycle_and_self_loop(
        self, cli_runner: CliRunner, tmp_path: pathlib.Path
    ) -> None:
        """JSON output separates cycles (errors) from self-loops (warnings)."""
        d = _make_graph_dict(
            {
                "a==1.0": {
                    "edges": [{"key": "b==1.0", "req_type": "install", "req": "b"}]
                },
                "b==1.0": {
                    "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}]
                },
                "c==1.0": {"edges": []},
            }
        )
        # Add self-loop to c
        d["c==1.0"]["edges"].append(
            {"key": "c==1.0", "req_type": "install", "req": "c[extras]"}
        )
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(
            fromager, ["graph", "check", "--json", str(graph_file)]
        )
        data = json.loads(result.output)
        assert data["acyclic"]["pass"] is False
        assert len(data["acyclic"]["cycles"]) == 1
        assert "CYCLE" in data["acyclic"]["cycles"][0]
        assert len(data["acyclic"]["self_loops"]) == 1
        assert "SELF-LOOP" in data["acyclic"]["self_loops"][0]

    def test_empty_graph(self, cli_runner: CliRunner, tmp_path: pathlib.Path) -> None:
        """Graph with only ROOT node passes all checks."""
        d = {
            "": {
                "download_url": "",
                "pre_built": False,
                "version": "0",
                "canonicalized_name": "",
                "edges": [],
            }
        }
        graph_file = _write_graph(tmp_path, d)
        result = cli_runner.invoke(fromager, ["graph", "check", str(graph_file)])
        assert result.exit_code == 0
        assert "All checks pass" in result.output
