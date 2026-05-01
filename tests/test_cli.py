import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager
from fromager.commands import commands


def test_migrate_config(
    testdata_path: pathlib.Path, tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    config027 = testdata_path / "config-0.27"
    expected = config027 / "expected"
    output = tmp_path / "output"

    result = cli_runner.invoke(
        fromager,
        [
            "migrate-config",
            "--settings-file",
            str(config027 / "settings.yaml"),
            "--envs-dir",
            str(config027 / "envs"),
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout

    expected_files = sorted(f.name for f in expected.iterdir())
    assert expected_files == sorted(f.name for f in output.iterdir())

    for filename in expected_files:
        expected_txt = expected.joinpath(filename).read_text()
        output_txt = output.joinpath(filename).read_text()
        assert output_txt == expected_txt


def test_fromager_version(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(fromager, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("fromager, version")


def test_output_dir_hidden_options(cli_runner: CliRunner) -> None:
    """--output-dir is visible in help; old per-directory flags are hidden."""
    result = cli_runner.invoke(fromager, ["--help"])
    assert "-O, --output-dir" in result.output
    lines = result.output.splitlines()
    option_lines = [line.strip() for line in lines if line.strip().startswith("-")]
    option_names = " ".join(option_lines)
    assert "--sdists-repo" not in option_names
    assert "--wheels-repo" not in option_names
    assert "--work-dir" not in option_names


def test_output_dir_sets_subdirectories(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Passing -O <dir> creates sdists-repo, wheels-repo, work-dir under it."""
    out = tmp_path / "my-output"
    out.mkdir()

    result = cli_runner.invoke(
        fromager,
        ["-O", str(out), "canonicalize", "some-package"],
    )
    assert result.exit_code == 0, result.output
    assert (out / "sdists-repo").is_dir()
    assert (out / "wheels-repo").is_dir()
    assert (out / "work-dir").is_dir()


def test_output_dir_overridden_by_explicit_flags(
    tmp_path: pathlib.Path, cli_runner: CliRunner
) -> None:
    """Explicit --sdists-repo takes precedence over --output-dir."""
    out = tmp_path / "base"
    out.mkdir()

    result = cli_runner.invoke(
        fromager,
        [
            "-O",
            str(out),
            "--sdists-repo",
            str(tmp_path / "custom-sdists"),
            "canonicalize",
            "some-package",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "custom-sdists").is_dir()
    assert (out / "wheels-repo").is_dir()
    assert (out / "work-dir").is_dir()
    assert not (out / "sdists-repo").exists()


KNOWN_COMMANDS: set[str] = {
    "bootstrap",
    "bootstrap-parallel",
    "build",
    "build-order",
    "build-parallel",
    "build-sequence",
    "canonicalize",
    "download-sequence",
    "find-updates",
    "graph",
    "lint",
    "lint-requirements",
    "list-overrides",
    "list-versions",
    "migrate-config",
    "minimize",
    "package",
    "stats",
    "step",
    "wheel-server",
}


def test_registered_eps() -> None:
    registered = {c.name for c in commands}
    assert registered == KNOWN_COMMANDS
