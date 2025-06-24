import json
import pathlib
import tempfile

from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.__main__ import main as fromager
from fromager.commands.minimize import _minimize_requirements
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType


def test_minimize_command() -> None:
    """Test the minimize command with sample data"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)

        # Create sample requirements.txt with overlapping dependencies
        requirements_file = tmp_path / "requirements.txt"
        requirements_file.write_text("""
# Test requirements file with overlapping dependencies
requests==2.28.1
urllib3>=1.26.0
click==8.1.3
rich==12.6.0
""")

        # Create sample graph.json
        graph_file = tmp_path / "graph.json"
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
                        "key": "urllib3==1.26.12",
                        "req_type": "toplevel",
                        "req": "urllib3==1.26.12",
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
            "urllib3==1.26.12": {
                "download_url": "https://pypi.org/simple/urllib3/urllib3-1.26.12.tar.gz",
                "pre_built": False,
                "version": "1.26.12",
                "canonicalized_name": "urllib3",
                "edges": [],
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
        }
        graph_file.write_text(json.dumps(graph_data))

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
                "minimize",
                str(requirements_file),
                str(graph_file),
            ],
        )

        # Check that command runs successfully
        assert result.exit_code == 0, f"Command failed with output: {result.output}"

        # Check that output contains expected packages (should exclude urllib3 as it's a dependency of requests)
        output_lines = [
            line.strip()
            for line in result.output.split("\n")
            if line.strip()
            and not line.strip().startswith(
                ("Original", "Minimized", "Removed", "INFO")
            )
        ]

        # Should contain requests, click, rich but not urllib3
        assert "requests==2.28.1" in output_lines
        assert "click==8.1.3" in output_lines
        assert "rich==12.6.0" in output_lines
        assert "urllib3>=1.26.0" not in output_lines

        # Check that 1 dependency was removed (urllib3)
        assert "Removed dependencies: 1" in result.output


def test_minimize_command_with_output_file() -> None:
    """Test the minimize command writes to output file"""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)

        # Create simple requirements file
        requirements_file = tmp_path / "requirements.txt"
        requirements_file.write_text("requests==2.28.1\n")

        # Create simple graph with no dependencies
        graph_file = tmp_path / "graph.json"
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
                ],
            },
            "requests==2.28.1": {
                "download_url": "https://pypi.org/simple/requests/requests-2.28.1.tar.gz",
                "pre_built": False,
                "version": "2.28.1",
                "canonicalized_name": "requests",
                "edges": [],
            },
        }
        graph_file.write_text(json.dumps(graph_data))

        output_file = tmp_path / "minimized.txt"

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
                "minimize",
                str(requirements_file),
                str(graph_file),
                "--output",
                str(output_file),
            ],
        )

        # Check that command runs successfully
        assert result.exit_code == 0, f"Command failed with output: {result.output}"
        assert output_file.exists()

        content = output_file.read_text().strip()
        assert content == "requests==2.28.1"


def test_minimize_requirements_function():
    """Test the _minimize_requirements function directly"""

    # Create a simple dependency graph
    graph = DependencyGraph()

    # Add top-level package that depends on another
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-a depends on package-c==1.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=1.0.0"),
        req_version=Version("1.0.0"),
    )

    # Add another top-level package
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-b==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # Test with matching version specifier
    requirements = [
        Requirement("package-a==1.0.0"),
        Requirement(
            "package-c>=1.0.0"
        ),  # This should be removed since package-a depends on it
        Requirement("package-b==1.0.0"),
    ]

    minimal = _minimize_requirements(requirements, graph)
    minimal_list = list(minimal)
    minimal_names = [req.name for req in minimal_list]

    assert "package-a" in minimal_names
    assert "package-b" in minimal_names
    assert "package-c" not in minimal_names  # Should be removed


def test_minimize_requirements_version_mismatch():
    """Test that requirements with version mismatches are NOT removed"""

    # Create a dependency graph
    graph = DependencyGraph()

    # Add top-level package that depends on another
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-a depends on package-c==1.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=1.0.0"),
        req_version=Version("1.0.0"),
    )

    # Test with NON-matching version specifier
    requirements = [
        Requirement("package-a==1.0.0"),
        Requirement(
            "package-c==2.0.0"
        ),  # This should NOT be removed - different version
    ]

    minimal = _minimize_requirements(requirements, graph)
    minimal_list = list(minimal)
    minimal_names = [req.name for req in minimal_list]

    assert "package-a" in minimal_names
    assert "package-c" in minimal_names  # Should NOT be removed due to version mismatch


def test_minimize_requirements_multiple_versions():
    """Test behavior with multiple versions of the same dependency"""

    # Create a dependency graph
    graph = DependencyGraph()

    # Add top-level packages
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a==1.0.0"),
        req_version=Version("1.0.0"),
    )

    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-b==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-a depends on package-c==1.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=1.0.0,<2.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-b depends on package-c==2.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-b"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=2.0.0"),
        req_version=Version("2.0.0"),
    )

    # Test requirements that include both versions
    requirements = [
        Requirement("package-a==1.0.0"),
        Requirement("package-b==1.0.0"),
        Requirement("package-c>=1.0.0,<2.0.0"),  # Should be removed (matches 1.0.0)
        Requirement("package-c>=2.0.0"),  # Should be removed (matches 2.0.0)
    ]

    minimal = _minimize_requirements(requirements, graph)

    # Should keep package-a and package-b (both top-level packages)
    # Both package-c requirements should be removed as they're dependencies
    minimal_list = list(minimal)
    assert len(minimal_list) == 2
    minimal_names = [req.name for req in minimal_list]
    assert "package-a" in minimal_names
    assert "package-b" in minimal_names
    assert "package-c" not in minimal_names  # Both should be removed


def test_minimize_command_nonexistent_files() -> None:
    """Test that the minimize command fails gracefully with nonexistent files"""

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
                "minimize",
                str(nonexistent_req),
                str(nonexistent_graph),
            ],
        )

        # Should fail because files don't exist
        assert result.exit_code != 0, "Command should fail with nonexistent files"


def test_minimize_requirements_multiple_entries_same_package():
    """Test that multiple entries for the same package are handled correctly"""

    # Create a dependency graph
    graph = DependencyGraph()

    # Add top-level package that depends on another
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-a depends on package-c==1.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=1.0.0"),
        req_version=Version("1.0.0"),
    )

    # Test with multiple entries for package-c - some should be removed, others kept
    requirements = [
        Requirement("package-a==1.0.0"),
        Requirement("package-c>=1.0.0"),  # Should be removed (matches dependency)
        Requirement("package-c==2.0.0"),  # Should be kept (doesn't match dependency)
        Requirement(
            'package-c>=1.0.0; python_version>="3.8"'
        ),  # Should be removed (matches dependency)
    ]

    minimal = _minimize_requirements(requirements, graph)

    # Should keep package-a and package-c==2.0.0
    minimal_list = list(minimal)
    assert len(minimal_list) == 2
    minimal_strs = [str(req) for req in minimal_list]
    assert "package-a==1.0.0" in minimal_strs
    assert "package-c==2.0.0" in minimal_strs


def test_minimize_requirements_exact_version_preserved():
    """Test that requirements with exact version specifications (==) are never removed"""

    # Create a dependency graph
    graph = DependencyGraph()

    # Add top-level package that depends on another
    graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("package-a==1.0.0"),
        req_version=Version("1.0.0"),
    )

    # package-a depends on package-c==1.0.0
    graph.add_dependency(
        parent_name=canonicalize_name("package-a"),
        parent_version=Version("1.0.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("package-c>=1.0.0"),
        req_version=Version("1.0.0"),
    )

    # Test with both exact and flexible version specifications
    requirements = [
        Requirement("package-a==1.0.0"),
        Requirement("package-c>=1.0.0"),  # Should be removed (flexible version)
        Requirement("package-c==1.0.0"),  # Should be kept (exact version)
    ]

    minimal = _minimize_requirements(requirements, graph)
    minimal_list = list(minimal)

    # Should keep package-a and the exact version of package-c
    assert len(minimal_list) == 2
    minimal_strs = [str(req) for req in minimal_list]
    assert "package-a==1.0.0" in minimal_strs
    assert "package-c==1.0.0" in minimal_strs
    assert "package-c>=1.0.0" not in minimal_strs
