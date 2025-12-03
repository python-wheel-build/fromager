import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager


def test_requirements_allows_duplicates(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that requirements.txt files allow duplicate package names with different versions."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("requests==2.28.0\nrequests==2.29.0\nnumpy==1.24.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(requirements_file)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Successfully validated 1 file(s)" in result.stdout


def test_requirements_allows_duplicates_with_markers(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that requirements.txt files allow duplicate package names with different markers."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text(
        'requests==2.28.0; python_version < "3.10"\n'
        'requests==2.29.0; python_version >= "3.10"\n'
    )

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(requirements_file)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Successfully validated 1 file(s)" in result.stdout


def test_requirements_allows_same_package_multiple_times(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that requirements.txt files allow the same package multiple times (for multi-version builds)."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("numpy==1.24.0\nnumpy==1.25.0\nnumpy==1.26.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(requirements_file)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Successfully validated 1 file(s)" in result.stdout


def test_constraints_rejects_duplicates(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that constraints.txt files reject duplicate package names."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("requests==2.28.0\nrequests==2.29.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 1
    assert "Duplicate entry" in result.output
    assert "requests==2.28.0" in result.output


def test_constraints_rejects_duplicates_with_same_marker(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that constraints.txt files reject duplicate package names with the same marker."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(
        'requests==2.28.0; python_version < "3.10"\n'
        'requests==2.29.0; python_version < "3.10"\n'
    )

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 1
    assert "Duplicate entry" in result.output


def test_constraints_allows_different_markers(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that constraints.txt files allow the same package with different markers."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(
        'requests==2.28.0; python_version < "3.10"\n'
        'requests==2.29.0; python_version >= "3.10"\n'
    )

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Successfully validated 1 file(s)" in result.stdout


def test_global_constraints_enforces_uniqueness(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that files ending with 'constraints.txt' (like global-constraints.txt) enforce uniqueness."""
    constraints_file = tmp_path / "global-constraints.txt"
    constraints_file.write_text("numpy==1.24.0\nnumpy==1.25.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 1
    assert "Duplicate entry" in result.output


def test_mixed_files_validation(tmp_path: pathlib.Path, cli_runner: CliRunner) -> None:
    """Test validating both requirements.txt and constraints.txt files together."""
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("requests==2.28.0\nrequests==2.29.0\n")

    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("numpy==1.24.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(requirements_file), str(constraints_file)],
    )

    assert result.exit_code == 0, result.stdout
    assert "Successfully validated 2 file(s)" in result.stdout


def test_constraints_rejects_extras(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that constraints.txt files reject packages with extras."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("requests[security]==2.28.0\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 1
    assert "Constraints files cannot contain extra dependencies" in result.output


def test_constraints_requires_version_specifier(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that constraints.txt files require version specifiers."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("requests\n")

    result = cli_runner.invoke(
        fromager,
        ["lint-requirements", str(constraints_file)],
    )

    assert result.exit_code == 1
    assert "Constraints must have a version specifier" in result.output
