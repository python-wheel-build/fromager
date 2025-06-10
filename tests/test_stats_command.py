import json
import pathlib
import tempfile

from click.testing import CliRunner

from fromager.__main__ import main as fromager


def test_stats_command() -> None:
    """Test the stats command with sample data"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)

        # Create sample requirements.txt
        requirements_file = tmp_path / "requirements.txt"
        requirements_file.write_text("""
# Test requirements file
requests==2.28.1
click==8.1.3
# Comment line should be ignored
rich==12.6.0
""")

        # Create sample graph.json
        graph_file = tmp_path / "graph.json"
        # Create a graph in the format expected by DependencyGraph
        graph_data = {
            "": {
                "download_url": "",
                "pre_built": False,
                "version": "0",
                "canonicalized_name": "",
                "edges": [
                    {
                        "key": "requests==2.28.1",
                        "req_type": "toplevel",
                        "req": "requests==2.28.1",
                    },
                    {
                        "key": "click==8.1.3",
                        "req_type": "toplevel",
                        "req": "click==8.1.3",
                    },
                    {
                        "key": "rich==12.6.0",
                        "req_type": "toplevel",
                        "req": "rich==12.6.0",
                    },
                ],
            },
            "requests==2.28.1": {
                "download_url": "https://pypi.org/simple/requests/requests-2.28.1.tar.gz",
                "pre_built": False,
                "version": "2.28.1",
                "canonicalized_name": "requests",
                "edges": [
                    {
                        "key": "urllib3==1.26.12",
                        "req_type": "install",
                        "req": "urllib3>=1.21.1,<1.27",
                    }
                ],
            },
            "click==8.1.3": {
                "download_url": "https://pypi.org/simple/click/click-8.1.3-py3-none-any.whl",
                "pre_built": True,
                "version": "8.1.3",
                "canonicalized_name": "click",
                "edges": [],
            },
            "rich==12.6.0": {
                "download_url": "https://pypi.org/simple/rich/rich-12.6.0.tar.gz",
                "pre_built": False,
                "version": "12.6.0",
                "canonicalized_name": "rich",
                "edges": [],
            },
            "urllib3==1.26.12": {
                "download_url": "https://pypi.org/simple/urllib3/urllib3-1.26.12.tar.gz",
                "pre_built": False,
                "version": "1.26.12",
                "canonicalized_name": "urllib3",
                "edges": [],
            },
        }
        graph_file.write_text(json.dumps(graph_data))

        # Ensure files exist
        assert requirements_file.exists(), "Requirements file should exist"
        assert graph_file.exists(), "Graph file should exist"

        # Create work directory structure
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        patches_dir = tmp_path / "patches"
        patches_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            fromager,
            [
                "--work-dir",
                str(work_dir),
                "--settings-dir",
                str(settings_dir),
                "--patches-dir",
                str(patches_dir),
                "stats",
                str(requirements_file),
                str(graph_file),
            ],
        )

        # Check that command runs successfully
        assert result.exit_code == 0, f"Command failed with output: {result.output}"

        # Check that output contains expected information
        assert "Build Statistics" in result.output
        assert "Requirements in requirements.txt" in result.output
        assert "Unique packages in build" in result.output
        assert "Pre-built packages" in result.output

        assert "3" in result.output  # 3 requirements
        assert "4" in result.output  # 4 unique packages


def test_stats_command_nonexistent_files() -> None:
    """Test that the stats command fails gracefully with nonexistent files"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)

        # Create work directory structure
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        patches_dir = tmp_path / "patches"
        patches_dir.mkdir()

        # Try with nonexistent files
        nonexistent_req = tmp_path / "nonexistent_requirements.txt"
        nonexistent_graph = tmp_path / "nonexistent_graph.json"

        runner = CliRunner()
        result = runner.invoke(
            fromager,
            [
                "--work-dir",
                str(work_dir),
                "--settings-dir",
                str(settings_dir),
                "--patches-dir",
                str(patches_dir),
                "stats",
                str(nonexistent_req),
                str(nonexistent_graph),
            ],
        )

        # Should fail because files don't exist
        assert result.exit_code != 0, "Command should fail with nonexistent files"
