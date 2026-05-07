"""Tests for the ``list-versions`` command cooldown enhancements (issue #1078).

Verifies that ``package list-versions`` shows upload timestamps, age in days,
and cooldown status via ``--format`` choices, and that
``--ignore-per-package-overrides`` correctly bypasses per-package overrides.
"""

import datetime
import json
import pathlib
import re
import typing

import pytest
import requests_mock
from click.testing import CliRunner

from fromager import candidate, resolver
from fromager.__main__ import main as fromager
from fromager.commands.package import _cooldown_status

_BOOTSTRAP_TIME = datetime.datetime(2026, 3, 26, 0, 0, 0, tzinfo=datetime.UTC)
_COOLDOWN_7_DAYS = 7
_PYPI_SIMPLE_JSON_CONTENT_TYPE = "application/vnd.pypi.simple.v1+json"

# Three versions at known ages relative to _BOOTSTRAP_TIME:
#   2.0.0  uploaded 2026-03-24 →  2 days old (within 7-day cooldown)
#   1.3.2  uploaded 2026-03-15 → 11 days old (outside cooldown)
#   1.2.2  uploaded 2026-01-01 → 84 days old (outside cooldown)
_PYPI_JSON_RESPONSE = {
    "meta": {"api-version": "1.1"},
    "name": "test-pkg",
    "files": [
        {
            "filename": "test_pkg-2.0.0.tar.gz",
            "url": "https://files.pythonhosted.org/packages/test_pkg-2.0.0.tar.gz",
            "hashes": {"sha256": "aaa"},
            "upload-time": "2026-03-24T00:00:00+00:00",
        },
        {
            "filename": "test_pkg-1.3.2.tar.gz",
            "url": "https://files.pythonhosted.org/packages/test_pkg-1.3.2.tar.gz",
            "hashes": {"sha256": "bbb"},
            "upload-time": "2026-03-15T00:00:00+00:00",
        },
        {
            "filename": "test_pkg-1.2.2.tar.gz",
            "url": "https://files.pythonhosted.org/packages/test_pkg-1.2.2.tar.gz",
            "hashes": {"sha256": "ccc"},
            "upload-time": "2026-01-01T00:00:00+00:00",
        },
    ],
}


def _extract_json_from_output(output: str) -> str:
    """Extract JSON array from CLI output that may contain log messages."""
    json_match = re.search(r"\[\s*\{.*\}\s*\]", output, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return "[]"


def _extract_csv_from_output(output: str) -> str:
    """Extract CSV content from output that may contain log messages."""
    lines = output.strip().split("\n")
    csv_lines = [line for line in lines if '"' in line and "," in line]
    return "\n".join(csv_lines)


@pytest.fixture(autouse=True)
def clear_resolver_cache() -> typing.Generator[None, None, None]:
    """Clear class-level resolver cache so mocked responses are always used."""
    resolver.BaseProvider.clear_cache()
    resolver.BaseProvider._cooldown_unsupported_warned.clear()
    yield


def _invoke_list_versions(
    cli_runner: CliRunner,
    extra_args: list[str] | None = None,
    min_release_age: int = 0,
) -> typing.Any:
    """Invoke ``fromager package list-versions`` with mocked PyPI."""
    args: list[str] = []
    if min_release_age:
        args.extend(["--min-release-age", str(min_release_age)])
    args.extend(["package", "list-versions"])
    if extra_args:
        args.extend(extra_args)
    args.append("test-pkg")

    with requests_mock.Mocker() as m:
        m.get(
            "https://pypi.org/simple/test-pkg/",
            json=_PYPI_JSON_RESPONSE,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        return cli_runner.invoke(fromager, args)


# ---------------------------------------------------------------------------
# Plain mode (no --details)
# ---------------------------------------------------------------------------


def test_list_versions_plain(cli_runner: CliRunner) -> None:
    """Without --details the command prints version numbers only."""
    result = _invoke_list_versions(cli_runner)
    assert result.exit_code == 0
    lines = [
        line
        for line in result.stdout.strip().split("\n")
        if not line.startswith("WARNING")
    ]
    versions = [line.strip() for line in lines if line.strip()]
    assert "1.2.2" in versions
    assert "1.3.2" in versions
    assert "2.0.0" in versions


def test_list_versions_plain_with_cooldown_filters_blocked(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain mode filters out cooldown-blocked versions."""
    original_init = candidate.Cooldown.__init__

    def patched_init(
        self: candidate.Cooldown, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        original_init(self, *args, **kwargs)
        self.bootstrap_time = _BOOTSTRAP_TIME

    monkeypatch.setattr(candidate.Cooldown, "__init__", patched_init)

    result = _invoke_list_versions(cli_runner, min_release_age=_COOLDOWN_7_DAYS)
    assert result.exit_code == 0
    lines = [
        line
        for line in result.stdout.strip().split("\n")
        if not line.startswith("WARNING")
    ]
    versions = [line.strip() for line in lines if line.strip()]
    assert "2.0.0" not in versions
    assert "1.3.2" in versions
    assert "1.2.2" in versions


# ---------------------------------------------------------------------------
# Detailed JSON output
# ---------------------------------------------------------------------------


def test_list_versions_json_no_cooldown(cli_runner: CliRunner) -> None:
    """--format json without cooldown shows upload times and empty cooldown."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "json"],
    )
    assert result.exit_code == 0

    data = json.loads(_extract_json_from_output(result.stdout))
    assert len(data) == 3

    # Verify structure
    for row in data:
        assert "package" in row
        assert "version" in row
        assert "upload_time" in row
        assert "age_days" in row
        assert "cooldown" in row
        assert row["package"] == "test-pkg"
        assert row["cooldown"] == ""  # no cooldown configured

    versions = [row["version"] for row in data]
    assert versions == ["1.2.2", "1.3.2", "2.0.0"]

    # Upload times should be populated
    assert all(row["upload_time"] != "" for row in data)
    assert all(row["age_days"] != "" for row in data)


def test_list_versions_json_with_cooldown(cli_runner: CliRunner) -> None:
    """--format json with cooldown marks blocked/allowed versions correctly."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "json"],
        min_release_age=_COOLDOWN_7_DAYS,
    )
    assert result.exit_code == 0

    data = json.loads(_extract_json_from_output(result.stdout))
    assert len(data) == 3

    status_by_version = {row["version"]: row["cooldown"] for row in data}
    # 2.0.0 is within 7-day cooldown (2 days old relative to ~now, but the
    # exact status depends on when the test runs).  For a reliable assertion,
    # check that at least one version has a non-empty cooldown status.
    assert any(s in ("blocked", "available") for s in status_by_version.values())


def test_list_versions_json_with_fixed_cooldown(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a fixed bootstrap_time, verify exact cooldown statuses."""
    original_init = candidate.Cooldown.__init__

    def patched_init(
        self: candidate.Cooldown, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        original_init(self, *args, **kwargs)
        self.bootstrap_time = _BOOTSTRAP_TIME

    monkeypatch.setattr(candidate.Cooldown, "__init__", patched_init)

    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "json"],
        min_release_age=_COOLDOWN_7_DAYS,
    )
    assert result.exit_code == 0

    data = json.loads(_extract_json_from_output(result.stdout))
    status_by_version = {row["version"]: row for row in data}

    # 2.0.0 uploaded 2026-03-24, bootstrap 2026-03-26, age=2 days → blocked
    assert status_by_version["2.0.0"]["cooldown"] == "blocked"
    assert status_by_version["2.0.0"]["age_days"] == "2"

    # 1.3.2 uploaded 2026-03-15, age=11 days → allowed
    assert status_by_version["1.3.2"]["cooldown"] == "available"
    assert status_by_version["1.3.2"]["age_days"] == "11"

    # 1.2.2 uploaded 2026-01-01, age=84 days → allowed
    assert status_by_version["1.2.2"]["cooldown"] == "available"
    assert status_by_version["1.2.2"]["age_days"] == "84"


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


def test_list_versions_csv(cli_runner: CliRunner) -> None:
    """--format csv produces valid CSV with expected columns."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "csv"],
    )
    assert result.exit_code == 0

    csv_output = _extract_csv_from_output(result.stdout)
    lines = csv_output.strip().split("\n")
    assert len(lines) == 4  # header + 3 data rows

    header = lines[0]
    assert '"package"' in header
    assert '"version"' in header
    assert '"upload_time"' in header
    assert '"age_days"' in header
    assert '"cooldown"' in header


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------


def test_list_versions_table(cli_runner: CliRunner) -> None:
    """--format table shows a Rich table."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "table"],
    )
    assert result.exit_code == 0
    assert "Versions for test-pkg" in result.stdout
    assert "Version" in result.stdout
    assert "Upload Time" in result.stdout
    assert "Age (days)" in result.stdout
    assert "2.0.0" in result.stdout
    assert "1.3.2" in result.stdout
    assert "1.2.2" in result.stdout


def test_list_versions_table_with_cooldown(cli_runner: CliRunner) -> None:
    """When cooldown is active the table includes a Cooldown column."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "table"],
        min_release_age=_COOLDOWN_7_DAYS,
    )
    assert result.exit_code == 0
    assert "Cooldown" in result.stdout


def test_list_versions_table_no_cooldown_column(
    cli_runner: CliRunner,
) -> None:
    """Without cooldown the table omits the Cooldown column."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "table"],
    )
    assert result.exit_code == 0
    assert "Cooldown" not in result.stdout


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


def test_list_versions_output_file(
    cli_runner: CliRunner, tmp_path: pathlib.Path
) -> None:
    """--output writes JSON to a file instead of stdout."""
    output_file = tmp_path / "versions.json"
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "json", "--output", str(output_file)],
    )
    assert result.exit_code == 0
    assert output_file.exists()

    data = json.loads(output_file.read_text())
    assert isinstance(data, list)
    assert len(data) == 3


def test_list_versions_output_ignored_for_plain_formats(
    cli_runner: CliRunner, tmp_path: pathlib.Path
) -> None:
    """--output is ignored with a warning for 'versions' and 'requirements' formats."""
    output_file = tmp_path / "versions.txt"
    for fmt in ("versions", "requirements"):
        result = _invoke_list_versions(
            cli_runner,
            extra_args=["--format", fmt, "--output", str(output_file)],
        )
        assert result.exit_code == 0
        assert not output_file.exists(), (
            f"--output should be ignored for --format {fmt}"
        )
        assert "Warning: --output option is ignored" in result.output


# ---------------------------------------------------------------------------
# --ignore-per-package-overrides
# ---------------------------------------------------------------------------


def test_list_versions_ignore_per_package_overrides(
    cli_runner: CliRunner,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--ignore-per-package-overrides uses global cooldown, ignoring per-package override.

    Set up a per-package override of min_release_age=0 (exempt) and verify
    that --ignore-per-package-overrides still shows cooldown status based
    on the global --min-release-age.
    """
    original_init = candidate.Cooldown.__init__

    def patched_init(
        self: candidate.Cooldown, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        original_init(self, *args, **kwargs)
        self.bootstrap_time = _BOOTSTRAP_TIME

    monkeypatch.setattr(candidate.Cooldown, "__init__", patched_init)

    # Create per-package override with min_release_age=0 (exempted)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True)
    pkg_settings = settings_dir / "test_pkg.yaml"
    pkg_settings.write_text("resolver_dist:\n  min_release_age: 0\n")

    # Without --ignore-per-package-overrides: cooldown is disabled (per-package=0)
    result_with_override = _invoke_with_settings(
        cli_runner,
        settings_dir=settings_dir,
        extra_args=["--format", "json"],
        min_release_age=_COOLDOWN_7_DAYS,
    )
    assert result_with_override.exit_code == 0
    data_with = json.loads(_extract_json_from_output(result_with_override.stdout))
    # Per-package override=0 means no cooldown → all empty status
    for row in data_with:
        assert row["cooldown"] == ""

    # With --ignore-per-package-overrides: global cooldown applies
    result_ignore = _invoke_with_settings(
        cli_runner,
        settings_dir=settings_dir,
        extra_args=[
            "--format",
            "json",
            "--ignore-per-package-overrides",
        ],
        min_release_age=_COOLDOWN_7_DAYS,
    )
    assert result_ignore.exit_code == 0
    data_ignore = json.loads(_extract_json_from_output(result_ignore.stdout))
    status_by_version = {row["version"]: row["cooldown"] for row in data_ignore}
    assert status_by_version["2.0.0"] == "blocked"
    assert status_by_version["1.3.2"] == "available"


def _invoke_with_settings(
    cli_runner: CliRunner,
    settings_dir: pathlib.Path,
    extra_args: list[str] | None = None,
    min_release_age: int = 0,
) -> typing.Any:
    """Invoke ``fromager package list-versions`` with settings dir and mocked PyPI."""
    args: list[str] = ["--settings-dir", str(settings_dir)]
    if min_release_age:
        args.extend(["--min-release-age", str(min_release_age)])
    args.extend(["package", "list-versions"])
    if extra_args:
        args.extend(extra_args)
    args.append("test-pkg")

    with requests_mock.Mocker() as m:
        m.get(
            "https://pypi.org/simple/test-pkg/",
            json=_PYPI_JSON_RESPONSE,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        return cli_runner.invoke(fromager, args)


# ---------------------------------------------------------------------------
# Requirements format
# ---------------------------------------------------------------------------


def test_list_versions_requirements_format(cli_runner: CliRunner) -> None:
    """--format requirements outputs name==version pins."""
    result = _invoke_list_versions(
        cli_runner,
        extra_args=["--format", "requirements"],
    )
    assert result.exit_code == 0
    lines = [
        line
        for line in result.stdout.strip().split("\n")
        if line.startswith("test-pkg==")
    ]
    assert len(lines) == 3
    assert "test-pkg==2.0.0" in lines


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_cooldown_status_no_cooldown() -> None:
    """No cooldown configured returns empty string."""
    assert _cooldown_status(datetime.datetime.now(datetime.UTC), None, True) == ""


def test_cooldown_status_blocked() -> None:
    """Upload within cooldown window returns 'blocked'."""
    cooldown = candidate.Cooldown(
        min_age=datetime.timedelta(days=7),
        bootstrap_time=_BOOTSTRAP_TIME,
    )
    recent_upload = datetime.datetime(2026, 3, 24, 0, 0, 0, tzinfo=datetime.UTC)
    assert _cooldown_status(recent_upload, cooldown, True) == "blocked"


def test_cooldown_status_allowed() -> None:
    """Upload outside cooldown window returns 'available'."""
    cooldown = candidate.Cooldown(
        min_age=datetime.timedelta(days=7),
        bootstrap_time=_BOOTSTRAP_TIME,
    )
    old_upload = datetime.datetime(2026, 3, 15, 0, 0, 0, tzinfo=datetime.UTC)
    assert _cooldown_status(old_upload, cooldown, True) == "available"


def test_cooldown_status_skipped() -> None:
    """Missing upload_time with unsupported provider returns 'skipped'."""
    cooldown = candidate.Cooldown(
        min_age=datetime.timedelta(days=7),
        bootstrap_time=_BOOTSTRAP_TIME,
    )
    assert _cooldown_status(None, cooldown, False) == "skipped"


def test_cooldown_status_fail_closed() -> None:
    """Missing upload_time with supported provider returns 'blocked' (fail-closed)."""
    cooldown = candidate.Cooldown(
        min_age=datetime.timedelta(days=7),
        bootstrap_time=_BOOTSTRAP_TIME,
    )
    assert _cooldown_status(None, cooldown, True) == "blocked"
