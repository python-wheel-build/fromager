import pathlib
import typing
import warnings

import pytest
import pytest_socket
from click.testing import CliRunner

from fromager import context, packagesettings
from fromager.packagesettings import SbomSettings

TESTDATA_PATH = pathlib.Path(__file__).parent.absolute() / "testdata"
E2E_PATH = pathlib.Path(__file__).parent.parent.absolute() / "e2e"
_blocked_network_attempts: set[tuple[str, str]] = set()


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
    network_marker = (
        pytest.mark.enable_socket
        if config.getoption("--with-network")
        else pytest.mark.skip(reason="need --with-network option to run")
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(network_marker)


def pytest_warning_recorded(
    warning_message: warnings.WarningMessage,
    when: str,
    nodeid: str,
    location: tuple[str, int, str] | None,
) -> None:
    """Record blocked socket attempts."""
    # pytest-socket has no warning category; assume warnings come from its module.
    if warning_message.filename == pytest_socket.__file__:
        _blocked_network_attempts.add((nodeid, str(warning_message.message)))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail on blocked requests even when their exceptions were caught."""
    # Caught socket errors and ignored background futures can leave tests passing.
    # Fail the session if any blocked attempts were recorded.
    if _blocked_network_attempts and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """List tests that attempted unexpected network access."""
    if not _blocked_network_attempts:
        return

    terminalreporter.write_sep("=", "unexpected network attempts")
    for nodeid, message in sorted(_blocked_network_attempts):
        terminalreporter.write_line(f"{nodeid}: {message}")


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
