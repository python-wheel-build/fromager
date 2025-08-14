import json
import pathlib
import re

from click.testing import CliRunner

from fromager.__main__ import main as fromager


def _extract_json_from_output(output: str) -> str:
    """Extract JSON content from output that may contain log messages."""
    # Find JSON array in the output
    json_match = re.search(r"\[\s*\{.*\}\s*\]", output, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return "[]"


def _extract_csv_from_output(output: str) -> str:
    """Extract CSV content from output that may contain log messages."""
    lines = output.strip().split("\n")
    # Find lines that look like CSV (contain quotes and commas)
    csv_lines = [line for line in lines if '"' in line and "," in line]
    return "\n".join(csv_lines)


def test_list_overrides_basic(
    testdata_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test basic list-overrides functionality without --details."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"

    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
        ],
    )
    assert result.exit_code == 0
    assert "test-other-pkg" in result.stdout
    assert "test-pkg" in result.stdout
    assert "test-pkg-library" in result.stdout


def test_list_overrides_details_table(
    testdata_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test list-overrides --details with table format (default)."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"

    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--details",
        ],
    )
    assert result.exit_code == 0
    assert "Package Overrides" in result.stdout
    assert "test-other-pkg" in result.stdout
    assert "test-pkg" in result.stdout
    assert "test-pkg-library" in result.stdout


def test_list_overrides_details_json(
    testdata_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test list-overrides --details --format json."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"

    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--details",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0

    # Extract JSON from output (filtering out log messages)
    json_output = _extract_json_from_output(result.stdout)
    data = json.loads(json_output)
    assert isinstance(data, list)
    assert len(data) == 3

    # Check that we have the expected packages
    packages = [item["package"] for item in data]
    assert "test-other-pkg" in packages
    assert "test-pkg" in packages
    assert "test-pkg-library" in packages

    # Check structure of first item
    first_item = data[0]
    assert "package" in first_item
    assert "version" in first_item
    assert "patches" in first_item
    assert "plugin_hooks" in first_item
    assert "rocm" in first_item  # variant column


def test_list_overrides_details_csv(
    testdata_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test list-overrides --details --format csv."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"

    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--details",
            "--format",
            "csv",
        ],
    )
    assert result.exit_code == 0

    # Extract CSV from output (filtering out log messages)
    csv_output = _extract_csv_from_output(result.stdout)
    lines = csv_output.strip().split("\n")
    assert len(lines) == 4  # header + 3 data rows

    # Check header
    header = lines[0]
    assert '"package"' in header
    assert '"version"' in header
    assert '"patches"' in header
    assert '"plugin_hooks"' in header
    assert '"rocm"' in header  # variant column

    # Check data rows
    assert any("test-other-pkg" in line for line in lines[1:])
    assert any("test-pkg" in line for line in lines[1:])
    assert any("test-pkg-library" in line for line in lines[1:])


def test_list_overrides_output_file(
    testdata_path: pathlib.Path, cli_runner: CliRunner, tmp_path: pathlib.Path
) -> None:
    """Test list-overrides with output file."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"
    output_file = tmp_path / "output.json"

    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--details",
            "--format",
            "json",
            "--output",
            str(output_file),
        ],
    )
    assert result.exit_code == 0
    # stdout may contain log messages, but should not contain the JSON data
    assert "test-other-pkg" not in result.stdout
    assert "test-pkg" not in result.stdout
    assert "test-pkg-library" not in result.stdout

    # Check that file was created and contains valid JSON
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert isinstance(data, list)
    assert len(data) == 3


def test_list_overrides_format_option_help(cli_runner: CliRunner) -> None:
    """Test that the format option shows the correct choices in help."""
    result = cli_runner.invoke(
        fromager,
        ["list-overrides", "--help"],
    )
    assert result.exit_code == 0
    assert "--format [table|csv|json]" in result.stdout
    assert "requires --details" in result.stdout


def test_list_overrides_warnings_without_details(
    testdata_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Test that warnings are shown when using format/output without details."""
    settings_file = testdata_path / "context" / "overrides" / "settings.yaml"
    patches_dir = testdata_path / "context" / "overrides" / "patches"

    # Test format warning
    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--format",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert (
        "Warning: --format option is ignored when --details is not used"
        in result.output
    )
    assert "test-other-pkg" in result.output

    # Test output warning
    result = cli_runner.invoke(
        fromager,
        [
            "--settings-file",
            str(settings_file),
            "--patches-dir",
            str(patches_dir),
            "list-overrides",
            "--output",
            "test.txt",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert (
        "Warning: --output option is ignored when --details is not used"
        in result.output
    )
    assert "test-other-pkg" in result.output
