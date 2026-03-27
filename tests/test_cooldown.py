"""Tests for the PyPI cooldown policy (issue #877).

The cooldown rejects package versions published fewer than N days ago,
protecting against supply-chain attacks where a malicious version is
published and immediately pulled in by automated builds.
"""

import datetime
import logging
import pathlib
import typing
from collections import defaultdict

import pytest
import requests_mock
import resolvelib
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, resolver
from fromager.context import Cooldown

_BOOTSTRAP_TIME = datetime.datetime(2026, 3, 26, 0, 0, 0, tzinfo=datetime.UTC)
_COOLDOWN_7_DAYS = datetime.timedelta(days=7)
# cutoff = 2026-03-19T00:00:00Z

# Use PEP 691 JSON format — pypi_simple reliably parses upload-time from JSON.
_PYPI_SIMPLE_JSON_CONTENT_TYPE = "application/vnd.pypi.simple.v1+json"

# Three versions at known ages:
#   2.0.0  uploaded 2026-03-24 →  2 days old (within cooldown)
#   1.3.2  uploaded 2026-03-15 → 11 days old (outside cooldown)
#   1.2.2  uploaded 2026-01-01 → 84 days old (outside cooldown)
_cooldown_json_response = {
    "meta": {"api-version": "1.1"},
    "name": "test-pkg",
    "files": [
        {
            "filename": "test_pkg-2.0.0-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/packages/test_pkg-2.0.0-py3-none-any.whl",
            "hashes": {"sha256": "aaa"},
            "upload-time": "2026-03-24T00:00:00+00:00",
        },
        {
            "filename": "test_pkg-1.3.2-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/packages/test_pkg-1.3.2-py3-none-any.whl",
            "hashes": {"sha256": "bbb"},
            "upload-time": "2026-03-15T00:00:00+00:00",
        },
        {
            "filename": "test_pkg-1.2.2-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/packages/test_pkg-1.2.2-py3-none-any.whl",
            "hashes": {"sha256": "ccc"},
            "upload-time": "2026-01-01T00:00:00+00:00",
        },
    ],
}

_all_recent_json_response = {
    "meta": {"api-version": "1.1"},
    "name": "test-pkg",
    "files": [
        {
            "filename": "test_pkg-2.0.0-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/packages/test_pkg-2.0.0-py3-none-any.whl",
            "hashes": {"sha256": "aaa"},
            "upload-time": "2026-03-25T00:00:00+00:00",
        },
        {
            "filename": "test_pkg-1.3.2-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/packages/test_pkg-1.3.2-py3-none-any.whl",
            "hashes": {"sha256": "bbb"},
            "upload-time": "2026-03-24T00:00:00+00:00",
        },
    ],
}

_COOLDOWN = Cooldown(
    min_age=_COOLDOWN_7_DAYS,
    bootstrap_time=_BOOTSTRAP_TIME,
)


@pytest.fixture(autouse=True)
def clear_resolver_cache() -> typing.Generator[None, None, None]:
    """Clear the class-level resolver cache before each test.

    BaseProvider.resolver_cache is a ClassVar that persists across test
    instances. Without clearing it, candidates fetched in one test are reused
    by subsequent tests, bypassing mocked HTTP responses and producing
    incorrect results.
    """
    resolver.BaseProvider.clear_cache()
    yield


def test_cooldown_filters_recent_version(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Versions within the cooldown window are skipped; older ones are selected."""
    monkeypatch.setattr(resolver, "DEBUG_RESOLVER", "1")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, cooldown=_COOLDOWN)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())
        with caplog.at_level(logging.DEBUG, logger="fromager.resolver"):
            result = rslvr.resolve([Requirement("test-pkg")])

        candidate = result.mapping["test-pkg"]
        # 2.0.0 is 2 days old (within cooldown); 1.3.2 is 11 days old (outside).
        assert str(candidate.version) == "1.3.2"
        # 2.0.0 should be logged as skipped; 1.3.2 should not.
        assert "skipping 2.0.0" in caplog.text
        assert "cooldown" in caplog.text
        assert "skipping 1.3.2" not in caplog.text


def test_cooldown_disabled_selects_latest() -> None:
    """Without a cooldown the resolver selects the latest version as normal."""
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=False)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())
        result = rslvr.resolve([Requirement("test-pkg")])

        candidate = result.mapping["test-pkg"]
        assert str(candidate.version) == "2.0.0"


def test_cooldown_all_blocked_raises_informative_error() -> None:
    """When all candidates are within the cooldown window the error says so."""
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_all_recent_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, cooldown=_COOLDOWN)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())

        with pytest.raises(resolvelib.resolvers.ResolverException) as exc_info:
            rslvr.resolve([Requirement("test-pkg")])

        msg = str(exc_info.value)
        assert "2 candidate(s)" in msg
        assert "7-day cooldown window" in msg


def test_cooldown_rejects_candidate_without_upload_time(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate with no upload_time is rejected when a cooldown is active (fail closed)."""
    monkeypatch.setattr(resolver, "DEBUG_RESOLVER", "1")
    candidate = resolver.Candidate(
        name="test-pkg",
        version=Version("1.0.0"),
        url="https://example.com/test-pkg-1.0.0.tar.gz",
        upload_time=None,
    )
    provider = resolver.PyPIProvider(cooldown=_COOLDOWN)
    req = Requirement("test-pkg")
    requirements: typing.Any = defaultdict(list)
    requirements["test-pkg"].append(req)
    incompatibilities: typing.Any = defaultdict(list)

    with caplog.at_level(logging.DEBUG, logger="fromager.resolver"):
        result = provider.validate_candidate(
            "test-pkg", requirements, incompatibilities, candidate
        )

    assert result is False
    assert "upload_time unknown" in caplog.text
    assert "1.0.0" in caplog.text


def test_cooldown_missing_timestamp_error_message() -> None:
    """Resolution failure due to missing timestamps produces a clear error message."""
    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.0.0-py3-none-any.whl",
                "url": "https://files.pythonhosted.org/packages/test_pkg-1.0.0-py3-none-any.whl",
                "hashes": {"sha256": "aaa"},
            },
        ],
    }
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=no_timestamp_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, cooldown=_COOLDOWN)

        with pytest.raises(resolvelib.resolvers.ResolverException) as exc_info:
            resolvelib.Resolver(provider, resolvelib.BaseReporter()).resolve(
                [Requirement("test-pkg")]
            )

        assert "upload timestamp" in str(exc_info.value)


def test_cooldown_applied_automatically_via_ctx(tmp_path: pathlib.Path) -> None:
    """ctx.pypi_cooldown propagates through both the direct and full resolve paths.

    Verifies two levels of the call stack without requiring a real build:
    - default_resolver_provider(ctx=ctx) picks up the cooldown directly
    - resolver.resolve(ctx=ctx) picks it up through find_and_invoke
    Plugin authors who call either function get cooldown enforcement for free.
    """
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        pypi_cooldown=_COOLDOWN,
    )

    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )

        # Via default_resolver_provider directly.
        provider = resolver.default_resolver_provider(
            ctx=ctx,
            req=Requirement("test-pkg"),
            sdist_server_url="https://pypi.org/simple/",
            include_sdists=True,
            include_wheels=True,
        )
        result = resolvelib.Resolver(provider, resolvelib.BaseReporter()).resolve(
            [Requirement("test-pkg")]
        )
        assert str(result.mapping["test-pkg"].version) == "1.3.2"

        # Via resolver.resolve() (exercises find_and_invoke path).
        resolver.BaseProvider.clear_cache()
        _, version = resolver.resolve(
            ctx=ctx,
            req=Requirement("test-pkg"),
            sdist_server_url="https://pypi.org/simple/",
            include_sdists=True,
            include_wheels=True,
        )
        assert str(version) == "1.3.2"


def test_wheel_only_resolution_ignores_cooldown_without_upload_time() -> None:
    """include_sdists=False suppresses the cooldown even when a cooldown is configured.

    Cache servers and prebuilt wheel servers (fromager wheel-server, Pulp,
    GitLab package registry) serve Simple HTML v1.0 with no upload_time.
    Cooldown only applies to sdist resolution from a public index; wheel-only
    lookups use a different trust model and must never fail-closed against
    servers that structurally cannot provide timestamps.
    """
    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": "https://cache.example.com/packages/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
                # no upload-time — as served by Simple HTML v1.0
            },
        ],
    }
    with requests_mock.Mocker() as r:
        r.get(
            "https://cache.example.com/simple/test-pkg/",
            json=no_timestamp_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(
            sdist_server_url="https://cache.example.com/simple/",
            include_sdists=False,
            include_wheels=True,
            cooldown=_COOLDOWN,  # cooldown configured but must not fire for wheel-only
        )
        result = resolvelib.Resolver(provider, resolvelib.BaseReporter()).resolve(
            [Requirement("test-pkg==1.3.2")]
        )
        assert str(result.mapping["test-pkg"].version) == "1.3.2"
