import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager


def test_fromager_version(cli_runner: CliRunner, e2e_path: pathlib.Path) -> None:
    graph_json = e2e_path / "build-parallel" / "graph.json"
    result = cli_runner.invoke(fromager, ["graph", "build-graph", str(graph_json)])
    assert result.exit_code == 0
    assert "1. flit-core==3.12.0, setuptools==80.8.0" in result.stdout
    assert "Building 16 packages in 4 rounds" in result.stdout
