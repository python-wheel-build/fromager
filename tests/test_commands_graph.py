import json
import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager


def test_fromager_version(cli_runner: CliRunner, e2e_path: pathlib.Path) -> None:
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(fromager, ["graph", "build-graph", str(graph_json)])
    assert result.exit_code == 0
    assert "1. flit-core==3.12.0, setuptools==80.8.0" in result.stdout
    assert "Building 16 packages in 4 rounds" in result.stdout


def test_graph_subset_basic(cli_runner: CliRunner, e2e_path: pathlib.Path) -> None:
    """Test basic subset extraction for a package with dependencies."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(
        fromager, ["graph", "subset", str(graph_json), "keyring"]
    )

    assert result.exit_code == 0
    subset_data = json.loads(result.stdout)

    # Should include keyring and its dependencies and dependents
    assert "keyring==25.6.0" in subset_data
    assert "jaraco-classes==3.4.0" in subset_data  # keyring dependency
    assert "imapautofiler==1.14.0" in subset_data  # depends on keyring
    assert "" in subset_data  # ROOT node should be included


def test_graph_subset_with_version(
    cli_runner: CliRunner, e2e_path: pathlib.Path
) -> None:
    """Test subset extraction with specific version filtering."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(
        fromager,
        ["graph", "subset", str(graph_json), "setuptools", "--version", "80.8.0"],
    )

    assert result.exit_code == 0
    subset_data = json.loads(result.stdout)

    # Should include only the specific version
    assert "setuptools==80.8.0" in subset_data
    # Should include packages that depend on setuptools
    assert "keyring==25.6.0" in subset_data
    assert "imapautofiler==1.14.0" in subset_data


def test_graph_subset_output_to_file(
    cli_runner: CliRunner, e2e_path: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Test subset extraction with output to file."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    output_file = tmp_path / "subset.json"

    result = cli_runner.invoke(
        fromager, ["graph", "subset", str(graph_json), "jinja2", "-o", str(output_file)]
    )

    assert result.exit_code == 0
    assert output_file.exists()

    with open(output_file) as f:
        subset_data = json.load(f)

    assert "jinja2==3.1.6" in subset_data
    assert "markupsafe==3.0.2" in subset_data  # jinja2 dependency
    assert "imapautofiler==1.14.0" in subset_data  # depends on jinja2


def test_graph_subset_nonexistent_package(
    cli_runner: CliRunner, e2e_path: pathlib.Path
) -> None:
    """Test error handling for non-existent package."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(
        fromager, ["graph", "subset", str(graph_json), "nonexistent"]
    )

    assert result.exit_code != 0
    assert "not found in graph" in result.output


def test_graph_subset_nonexistent_version(
    cli_runner: CliRunner, e2e_path: pathlib.Path
) -> None:
    """Test error handling for non-existent version of existing package."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(
        fromager,
        ["graph", "subset", str(graph_json), "setuptools", "--version", "999.0.0"],
    )

    assert result.exit_code != 0
    assert "not found in graph" in result.output


def test_graph_subset_structure_integrity(
    cli_runner: CliRunner, e2e_path: pathlib.Path
) -> None:
    """Test that subset graph maintains proper structure and references."""
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(fromager, ["graph", "subset", str(graph_json), "pyyaml"])

    assert result.exit_code == 0
    subset_data = json.loads(result.stdout)

    # Verify all referenced nodes exist
    for _node_key, node_data in subset_data.items():
        for edge in node_data.get("edges", []):
            assert edge["key"] in subset_data, (
                f"Referenced node {edge['key']} not found in subset"
            )

    # Verify PyYAML is included
    assert "pyyaml==6.0.2" in subset_data
    # Verify its dependent is included
    assert "imapautofiler==1.14.0" in subset_data
