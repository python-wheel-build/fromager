import pathlib
import typing

import pytest
from click.testing import CliRunner

from fromager import context, packagesettings

TESTDATA_PATH = pathlib.Path(__file__).parent.absolute() / "testdata"


@pytest.fixture
def testdata_path() -> typing.Generator[pathlib.Path, None, None]:
    yield TESTDATA_PATH


@pytest.fixture
def tmp_context(tmp_path: pathlib.Path) -> context.WorkContext:
    patches_dir = tmp_path / "overrides/patches"
    variant = "cpu"
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=patches_dir,
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
        variant=variant,
    )
    ctx.setup()
    return ctx


@pytest.fixture
def testdata_context(
    testdata_path: pathlib.Path, tmp_path: pathlib.Path
) -> context.WorkContext:
    overrides = testdata_path / "context" / "overrides"
    patches_dir = overrides / "patches"
    variant = "cpu"
    ctx = context.WorkContext(
        active_settings=packagesettings.Settings.from_files(
            settings_file=overrides / "settings.yaml",
            settings_dir=overrides / "settings",
            patches_dir=patches_dir,
            variant=variant,
            max_jobs=None,
        ),
        constraints_file=None,
        patches_dir=overrides / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
    )
    ctx.setup()
    return ctx


@pytest.fixture
def cli_runner(
    tmp_path: pathlib.Path,
) -> typing.Generator[CliRunner, None, None]:
    """Click CLI runner"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        yield runner
