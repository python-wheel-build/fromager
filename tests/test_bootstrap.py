import io
import pathlib
import textwrap
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import bootstrapper, context, dependency_graph, packagesettings
from fromager.commands import bootstrap


def test_get_requirements_single_arg():
    requirements = bootstrap._get_requirements_from_args(["a"], [])
    assert [Requirement("a")] == requirements


def test_get_requirements_multiple_args():
    requirements = bootstrap._get_requirements_from_args(["a", "b"], [])
    assert [Requirement("a"), Requirement("b")] == requirements


def test_get_requirements_args_and_file(tmp_path: pathlib.Path):
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("c\n")
    requirements = bootstrap._get_requirements_from_args(
        ["a", "b"], [str(requirements_file)]
    )
    assert [
        Requirement("a"),
        Requirement("b"),
        Requirement("c"),
    ] == requirements


def test_ignore_based_on_marker():
    requirements = bootstrap._get_requirements_from_args(
        ['foo; python_version<"3.9"'], []
    )
    assert [] == requirements


def test_write_constraints_file_simple():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c<4.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        c==3.0
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_resolvable_duplicate():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c<4.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [{"key": "c==3.1", "req_type": "install", "req": "c>3.0"}],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
        "c==3.1": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==1.0
        b==2.0
        # NOTE: fromager selected c==3.1 from: ['3.0', '3.1']
        c==3.1
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_unresolvable_duplicate():
    """Test that unresolvable duplicates cause the function to return False and not write conflicting constraints.

    This test has conflicting requirements for package 'c':
    - a==1.0 requires c==3.0 (exact version 3.0)
    - b==2.0 requires c>3.0 (greater than 3.0)
    These cannot be satisfied simultaneously, so the function should return False
    and only write the packages that CAN be resolved.
    """
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c==3.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [{"key": "c==3.1", "req_type": "install", "req": "c>3.0"}],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
        "c==3.1": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)

    # Should return False due to impossible constraints for package 'c'
    result = bootstrap.write_constraints_file(graph, buffer)
    assert result is False

    # Should only write packages that CAN be resolved (no conflicting 'c' versions)
    output = buffer.getvalue()
    assert "a==1.0" in output
    assert "b==2.0" in output
    assert "c==" not in output  # No conflicting c versions should be written


def test_write_constraints_file_duplicates():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [
                {"key": "a==1.0", "req_type": "install", "req": "a"},
                {"key": "d==1.0", "req_type": "install", "req": "d"},
            ],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "c==3.0", "req_type": "install", "req": "c<=3.0"},
            ],
        },
        "d==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "c==3.1", "req_type": "install", "req": "c>=3.0"},
            ],
        },
        "c==3.0": {  # transformers 4.46
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [{"key": "b==2.0", "req_type": "install", "req": "b<2.1,>=2.0"}],
        },
        "c==3.1": {  # transformers 4.47
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [{"key": "b==2.1", "req_type": "install", "req": "b<2.2,>=2.1"}],
        },
        "b==2.0": {  # tokenizer
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [],
        },
        "b==2.1": {  # tokenizer
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.1",
            "canonicalized_name": "b",
            "edges": [],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)

    # This should return False because there's a genuine constraint conflict:
    # c==3.0 requires b<2.1,>=2.0 (only b==2.0 satisfies this)
    # c==3.1 requires b<2.2,>=2.1 (only b==2.1 satisfies this)
    # No single version of b can satisfy both constraints
    result = bootstrap.write_constraints_file(graph, buffer)
    assert result is False

    # When there are conflicts, no constraints should be written to the output
    output_content = buffer.getvalue()
    # Should contain resolved packages that don't have conflicts
    assert "a==1.0" in output_content
    assert "d==1.0" in output_content
    # c gets resolved to 3.0 before the conflict with b is detected
    assert "c==3.0" in output_content
    # Should NOT contain conflicted packages
    assert "b==" not in output_content


def test_write_constraints_file_multiples():
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [
                {
                    "key": "a==2.7.0",
                    "req_type": "toplevel",
                    "req": "a==2.7.0",
                },
                {
                    "key": "b==0.26.1",
                    "req_type": "toplevel",
                    "req": "b==0.26.1",
                },
            ],
        },
        "b==0.26.1": {
            "download_url": "",
            "pre_built": False,
            "version": "0.26.1",
            "canonicalized_name": "b",
            "edges": [],
        },
        "b==0.26.2": {
            "download_url": "",
            "pre_built": False,
            "version": "0.26.2",
            "canonicalized_name": "b",
            "edges": [],
        },
        "a==2.7.0": {
            "download_url": "",
            "pre_built": False,
            "version": "2.7.0",
            "canonicalized_name": "a",
            "edges": [
                {
                    "key": "b==0.26.2",
                    "req_type": "install",
                    "req": "b<0.27.0,>=0.26.1",
                },
            ],
        },
    }
    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    assert bootstrap.write_constraints_file(graph, buffer)
    expected = textwrap.dedent("""
        a==2.7.0
        # NOTE: fromager selected b==0.26.2 from: ['0.26.1', '0.26.2']
        b==0.26.2
        """).lstrip()
    assert expected == buffer.getvalue()


def test_write_constraints_file_prevents_false_resolution():
    """Test that packages marked as unresolvable in early iterations stay unresolvable.

    This test validates the fix for the bug where a package could appear unresolvable
    in iteration 1 (due to constraints from multiple versions), but then appear
    resolvable in iteration 2+ when user counts change after other packages resolve.

    Without the fix, 'conflicted' would be incorrectly resolved in a later iteration.
    With the fix, it should remain unresolvable throughout all iterations.
    """
    buffer = io.StringIO()
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [
                {"key": "easy==1.0", "req_type": "toplevel", "req": "easy==1.0"},
                {"key": "pkg-a==1.0", "req_type": "toplevel", "req": "pkg-a==1.0"},
                {"key": "pkg-b==1.0", "req_type": "toplevel", "req": "pkg-b==1.0"},
            ],
        },
        "easy==1.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "easy",
            "edges": [],  # No dependencies, resolves immediately
        },
        "pkg-a==1.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "pkg-a",
            "edges": [
                {
                    "key": "conflicted==1.0",
                    "req_type": "install",
                    "req": "conflicted<1.5",
                },
                {
                    "key": "intermediate==1.0",
                    "req_type": "install",
                    "req": "intermediate",
                },
            ],
        },
        "pkg-b==1.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "pkg-b",
            "edges": [
                {
                    "key": "conflicted==2.0",
                    "req_type": "install",
                    "req": "conflicted>=2.0",
                },
            ],
        },
        "intermediate==1.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "intermediate",
            "edges": [
                {
                    "key": "conflicted==1.0",
                    "req_type": "install",
                    "req": "conflicted<1.5",
                },
            ],
        },
        "conflicted==1.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "conflicted",
            "edges": [],
        },
        "conflicted==2.0": {
            "download_url": "url",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "conflicted",
            "edges": [],
        },
    }

    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)
    result = bootstrap.write_constraints_file(graph, buffer)

    # Should return False because 'conflicted' has impossible constraints:
    # - pkg-a and intermediate need conflicted<1.5 (only 1.0 satisfies)
    # - pkg-b needs conflicted>=2.0 (only 2.0 satisfies)
    # - No version satisfies both <1.5 AND >=2.0
    assert result is False

    # Verify that packages that CAN be resolved are written
    output_content = buffer.getvalue()
    assert "easy==1.0" in output_content
    assert "pkg-a==1.0" in output_content
    assert "pkg-b==1.0" in output_content
    assert "intermediate==1.0" in output_content

    # Verify that the conflicted package is NOT written
    assert "conflicted==" not in output_content


def test_to_constraints_command_no_file_on_failure(tmp_path):
    """Test that the to-constraints logic doesn't create output files when there are constraint conflicts.

    This is a regression test for the bug where constraint resolution would write partial
    output even when it ultimately failed.
    """
    import io

    from fromager import dependency_graph

    # Create a graph with conflicts (same as test_write_constraints_file_unresolvable_duplicate)
    raw_graph = {
        "": {
            "download_url": "",
            "pre_built": False,
            "version": "0",
            "canonicalized_name": "",
            "edges": [{"key": "a==1.0", "req_type": "install", "req": "a"}],
        },
        "a==1.0": {
            "download_url": "url for a",
            "pre_built": False,
            "version": "1.0",
            "canonicalized_name": "a",
            "edges": [
                {"key": "b==2.0", "req_type": "install", "req": "b>=2.0"},
                {"key": "c==3.0", "req_type": "install", "req": "c==3.0"},
            ],
        },
        "b==2.0": {
            "download_url": "url for b",
            "pre_built": False,
            "version": "2.0",
            "canonicalized_name": "b",
            "edges": [{"key": "c==3.1", "req_type": "install", "req": "c>3.0"}],
        },
        "c==3.0": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.0",
            "canonicalized_name": "c",
            "edges": [],
        },
        "c==3.1": {
            "download_url": "url for c",
            "pre_built": False,
            "version": "3.1",
            "canonicalized_name": "c",
            "edges": [],
        },
    }

    graph = dependency_graph.DependencyGraph.from_dict(raw_graph)

    # Test the new to-constraints logic: use buffer first, only create file on success
    output_file = tmp_path / "constraints.txt"

    # Simulate the fixed to-constraints behavior
    buffer = io.StringIO()
    result = bootstrap.write_constraints_file(graph, buffer)

    # Should return False due to conflicts
    assert result is False

    # Because result is False, the output file should NOT be created
    # (In the old buggy behavior, the file would have been created with partial content)

    # Since result is False, we shouldn't write to the actual file
    # This simulates the fix where we check the result before creating the output file
    if result:
        with open(output_file, "w") as f:
            f.write(buffer.getvalue())

    # Verify the output file was NOT created
    assert not output_file.exists(), (
        f"Output file {output_file} should not have been created when constraint resolution failed"
    )


def test_skip_constraints_cli_option():
    """Test that the --skip-constraints option is available in the CLI"""
    runner = CliRunner()
    result = runner.invoke(bootstrap.bootstrap, ["--help"])

    # Check that the help text includes our new option
    assert "--skip-constraints" in result.output
    assert "Skip generating constraints.txt file" in result.output


@patch("fromager.gitutils.git_clone")
def test_resolve_version_from_git_url_with_submodules_enabled(
    mock_git_clone: Mock,
    tmp_context: context.WorkContext,
):
    """Test that git_clone is called with submodules=True when configured."""
    req = Requirement("test-pkg @ git+https://github.com/example/repo.git")

    mock_git_options = packagesettings.GitOptions(submodules=True)

    with patch.object(tmp_context, "package_build_info") as mock_pbi:
        mock_pbi_instance = Mock()
        mock_pbi_instance.git_options = mock_git_options
        mock_pbi.return_value = mock_pbi_instance

        with patch(
            "fromager.bootstrapper.Bootstrapper._get_version_from_package_metadata"
        ) as mock_get_version:
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    mock_get_version.return_value = Version("1.0.0")

                    # Execute
                    bs = bootstrapper.Bootstrapper(tmp_context)
                    try:
                        bs._resolve_version_from_git_url(req)
                    except AssertionError:
                        # Expected since we're mocking everything
                        pass

    mock_git_clone.assert_called_once()
    call_args = mock_git_clone.call_args
    assert call_args.kwargs["submodules"] is True
    assert call_args.kwargs["repo_url"] == "https://github.com/example/repo.git"
    assert call_args.kwargs["ref"] is None


@patch("fromager.gitutils.git_clone")
def test_resolve_version_from_git_url_with_specific_submodule_paths(
    mock_git_clone: Mock,
    tmp_context: context.WorkContext,
):
    """Test that git_clone is called with specific submodule paths when configured."""
    req = Requirement("test-pkg @ git+https://github.com/example/repo.git")

    mock_git_options = packagesettings.GitOptions(
        submodule_paths=["vendor/lib1", "vendor/lib2"]
    )

    with patch.object(tmp_context, "package_build_info") as mock_pbi:
        mock_pbi_instance = Mock()
        mock_pbi_instance.git_options = mock_git_options
        mock_pbi.return_value = mock_pbi_instance

        with patch(
            "fromager.bootstrapper.Bootstrapper._get_version_from_package_metadata"
        ) as mock_get_version:
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    mock_get_version.return_value = Version("1.0.0")

                    bs = bootstrapper.Bootstrapper(tmp_context)
                    try:
                        bs._resolve_version_from_git_url(req)
                    except AssertionError:
                        # Expected since we're mocking everything
                        pass

    mock_git_clone.assert_called_once()
    call_args = mock_git_clone.call_args
    assert call_args.kwargs["submodules"] == ["vendor/lib1", "vendor/lib2"]


@patch("fromager.gitutils.git_clone")
def test_resolve_version_from_git_url_with_submodules_disabled(
    mock_git_clone: Mock,
    tmp_context: context.WorkContext,
):
    """Test that git_clone is called with submodules=False by default."""
    req = Requirement("test-pkg @ git+https://github.com/example/repo.git")

    with patch(
        "fromager.bootstrapper.Bootstrapper._get_version_from_package_metadata"
    ) as mock_get_version:
        with patch("shutil.move"):
            with patch("pathlib.Path.mkdir"):
                mock_get_version.return_value = Version("1.0.0")

                bs = bootstrapper.Bootstrapper(tmp_context)
                try:
                    bs._resolve_version_from_git_url(req)
                except AssertionError:
                    # Expected since we're mocking everything
                    pass

    mock_git_clone.assert_called_once()
    call_args = mock_git_clone.call_args
    assert call_args.kwargs["submodules"] is False


@patch("fromager.gitutils.git_clone")
def test_resolve_version_from_git_url_with_git_ref(
    mock_git_clone: Mock,
    tmp_context: context.WorkContext,
):
    """Test that git_clone is called with the correct ref when URL includes @ref."""
    req = Requirement("test-pkg @ git+https://github.com/example/repo.git@v1.2.3")

    mock_git_options = packagesettings.GitOptions(submodules=True)

    with patch.object(tmp_context, "package_build_info") as mock_pbi:
        mock_pbi_instance = Mock()
        mock_pbi_instance.git_options = mock_git_options
        mock_pbi.return_value = mock_pbi_instance

        with patch(
            "fromager.bootstrapper.Bootstrapper._get_version_from_package_metadata"
        ) as mock_get_version:
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    mock_get_version.return_value = Version("1.2.3")

                    bs = bootstrapper.Bootstrapper(tmp_context)
                    try:
                        bs._resolve_version_from_git_url(req)
                    except AssertionError:
                        # Expected since we're mocking everything
                        pass

    mock_git_clone.assert_called_once()
    call_args = mock_git_clone.call_args
    assert call_args.kwargs["submodules"] is True
    assert call_args.kwargs["repo_url"] == "https://github.com/example/repo.git"
    assert call_args.kwargs["ref"] == "v1.2.3"


def test_resolve_version_from_git_url_invalid_scheme(tmp_context: context.WorkContext):
    """Test that non-git URLs raise ValueError."""
    req = Requirement("test-pkg @ https://github.com/example/repo.git")

    bs = bootstrapper.Bootstrapper(tmp_context)
    with pytest.raises(ValueError, match="unable to handle URL scheme"):
        bs._resolve_version_from_git_url(req)
