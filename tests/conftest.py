import pathlib
import typing

import pytest
from click.testing import CliRunner

from fromager import context, settings

TESTDATA_PATH = pathlib.Path(__file__).parent.absolute() / "testdata"


@pytest.fixture
def testdata_path() -> typing.Generator[pathlib.Path, None, None]:
    yield TESTDATA_PATH


@pytest.fixture
def tmp_context(tmp_path) -> context.WorkContext:
    ctx = context.WorkContext(
        active_settings=settings.Settings({}),
        constraints_file=None,
        patches_dir=tmp_path / "overrides/patches",
        envs_dir=tmp_path / "overrides/envs",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
    )
    ctx.setup()
    return ctx


@pytest.fixture
def testdata_context(testdata_path, tmp_path) -> context.WorkContext:
    overrides = testdata_path / "context" / "overrides"
    ctx = context.WorkContext(
        active_settings=settings.load(
            settings_file=overrides / "settings.yaml",
            settings_dir=overrides / "settings",
        ),
        constraints_file=None,
        patches_dir=overrides / "patches",
        envs_dir=overrides / "envs",
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
