import pathlib

from click.testing import CliRunner

from fromager.__main__ import main as fromager


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
