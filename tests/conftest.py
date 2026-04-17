import pathlib
import typing

import pytest
from click.testing import CliRunner

from fromager import context, packagesettings
from fromager.packagesettings import SbomSettings

TESTDATA_PATH = pathlib.Path(__file__).parent.absolute() / "testdata"
E2E_PATH = pathlib.Path(__file__).parent.parent.absolute() / "e2e"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--with-network",
        action="store_true",
        default=False,
        help="run tests that require network access",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--with-network"):
        return
    skip_network = pytest.mark.skip(reason="need --with-network option to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


@pytest.fixture
def testdata_path() -> typing.Generator[pathlib.Path, None, None]:
    yield TESTDATA_PATH


@pytest.fixture
def e2e_path() -> typing.Generator[pathlib.Path, None, None]:
    yield E2E_PATH


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
    )
    ctx.setup()
    return ctx


def make_sbom_ctx(
    tmp_path: pathlib.Path,
    sbom_settings: SbomSettings | None = None,
    package_overrides: dict[str, typing.Any] | None = None,
) -> context.WorkContext:
    """Create a minimal WorkContext with SBOM settings."""
    settings_file = packagesettings.SettingsFile(sbom=sbom_settings)
    settings = packagesettings.Settings(
        settings=settings_file,
        package_settings=[],
        patches_dir=tmp_path / "patches",
        variant="cpu",
        max_jobs=None,
    )
    if package_overrides is not None:
        ps = packagesettings.PackageSettings.from_mapping(
            "test-pkg",
            package_overrides,
            source="test",
            has_config=True,
        )
        settings._package_settings[ps.name] = ps
    return context.WorkContext(
        active_settings=settings,
        constraints_file=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )


@pytest.fixture
def cli_runner(
    tmp_path: pathlib.Path,
) -> typing.Generator[CliRunner, None, None]:
    """Click CLI runner"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        yield runner
