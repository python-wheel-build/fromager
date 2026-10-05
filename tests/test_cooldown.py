"""Tests for the release-age cooldown policy (issue #877).

The cooldown rejects package versions published fewer than N days ago,
protecting against supply-chain attacks where a malicious version is
published and immediately pulled in by automated builds.
"""

import datetime
import logging
import pathlib
import re
import typing

import pytest
import requests_mock
import resolvelib
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import (
    candidate,
    constraints,
    context,
    packagesettings,
    resolver,
    sources,
    wheels,
)
from fromager.commands import build as build_command
from fromager.packagesettings import WheelSettings
from fromager.requirements_file import RequirementType

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

_COOLDOWN = candidate.Cooldown(
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
    resolver.BaseProvider._cooldown_unsupported_warned.clear()
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
        # 2.0.0 should be logged as blocked; 1.3.2 should not appear in the summary.
        assert "cooldown blocked 1 version(s): 2.0.0" in caplog.text


def test_cooldown_disabled_selects_latest() -> None:
    """Without a cooldown the resolver selects the latest version as normal."""
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, cooldown=None)
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
        assert "published within the last 7 days (release-age cooldown" in msg


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

    with caplog.at_level(logging.DEBUG, logger="fromager.resolver"):
        result = provider.is_blocked_by_cooldown(candidate)

    assert result is True
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
    """ctx.cooldown propagates through resolver.resolve() to any provider.

    Cooldown is set on the provider by resolve() after find_and_invoke()
    returns it, so plugin authors do not need to handle cooldown themselves.
    """
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )

        _, version = resolver.resolve(
            ctx=ctx,
            req=Requirement("test-pkg"),
            sdist_server_url="https://pypi.org/simple/",
            include_sdists=True,
            include_wheels=True,
        )
        assert str(version) == "1.3.2"


def test_toplevel_equality_pin_bypasses_cooldown_via_resolve(
    tmp_path: pathlib.Path,
) -> None:
    """Top-level == pin threads through resolve() and bypasses cooldown end-to-end.

    Verifies the req_type plumbing in resolver.resolve() actually causes
    resolve_package_cooldown() to disable cooldown, allowing a recent version
    that would normally be filtered.
    """
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )

        _, version = resolver.resolve(
            ctx=ctx,
            req=Requirement("test-pkg==2.0.0"),
            sdist_server_url="https://pypi.org/simple/",
            include_sdists=True,
            include_wheels=True,
            req_type=RequirementType.TOP_LEVEL,
        )
        assert str(version) == "2.0.0"


def test_cooldown_applied_via_get_source_provider(tmp_path: pathlib.Path) -> None:
    """ctx.cooldown propagates through sources.get_source_provider() to any provider.

    The bootstrapper resolves sources via get_source_provider(), not resolver.resolve().
    This test ensures cooldown is applied on that path too, so plugin-provided
    providers cannot silently bypass the cooldown.
    """
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    provider = sources.get_source_provider(
        ctx=ctx,
        req=Requirement("test-pkg"),
        sdist_server_url="https://pypi.org/simple/",
    )

    assert provider.cooldown == _COOLDOWN


def test_non_pypi_index_allows_without_upload_time(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """resolve() against a non-pypi.org index warns and allows when upload_time is missing.

    PyPIProvider auto-detects supports_upload_time=False for any URL that is not
    https://pypi.org/simple, so missing timestamps on mirrors or internal indexes
    produce a warning rather than fail-closed rejection.
    """
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )
    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": "https://cache.example.com/packages/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
                # no upload-time — as served by Simple HTML v1.0 / PEP 503
            },
        ],
    }
    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                "https://cache.example.com/simple/test-pkg/",
                json=no_timestamp_response,
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            _, version = resolver.resolve(
                ctx=ctx,
                req=Requirement("test-pkg==1.3.2"),
                sdist_server_url="https://cache.example.com/simple/",
                include_sdists=False,
                include_wheels=True,
            )

    assert str(version) == "1.3.2"
    assert "cooldown check skipped" in caplog.text


def _make_ctx(
    tmp_path: pathlib.Path,
    *,
    cooldown: candidate.Cooldown | None,
    min_release_age: int | None = None,
) -> context.WorkContext:
    """Build a WorkContext with an optional per-package min_release_age setting."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(exist_ok=True)
    if min_release_age is not None:
        (settings_dir / "test-pkg.yaml").write_text(
            yaml.dump({"resolver_dist": {"min_release_age": min_release_age}})
        )
    return context.WorkContext(
        active_settings=packagesettings.Settings.from_files(
            settings_file=tmp_path / "settings.yaml",
            settings_dir=settings_dir,
            patches_dir=tmp_path / "patches",
            variant="cpu",
            max_jobs=None,
        ),
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=cooldown,
    )


def test_resolve_package_cooldown_inherits_global(tmp_path: pathlib.Path) -> None:
    """No per-package override returns the global cooldown unchanged."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(ctx, Requirement("test-pkg"))
    assert result is _COOLDOWN


def test_resolve_package_cooldown_disabled_per_package(tmp_path: pathlib.Path) -> None:
    """min_release_age=0 disables the cooldown for the package even when global is set."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN, min_release_age=0)
    result = resolver.resolve_package_cooldown(ctx, Requirement("test-pkg"))
    assert result is None


def test_resolve_package_cooldown_disabled_no_global(tmp_path: pathlib.Path) -> None:
    """min_release_age=0 with no global cooldown still returns None."""
    ctx = _make_ctx(tmp_path, cooldown=None, min_release_age=0)
    result = resolver.resolve_package_cooldown(ctx, Requirement("test-pkg"))
    assert result is None


def test_resolve_package_cooldown_override_days(tmp_path: pathlib.Path) -> None:
    """Positive per-package override creates a new Cooldown with the given days."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN, min_release_age=30)
    result = resolver.resolve_package_cooldown(ctx, Requirement("test-pkg"))
    assert result is not None
    assert result.min_age.days == 30
    # bootstrap_time is inherited from the global cooldown for a consistent cutoff.
    assert result.bootstrap_time == _COOLDOWN.bootstrap_time


def test_resolve_package_cooldown_override_no_global(tmp_path: pathlib.Path) -> None:
    """Positive per-package override works even without a global cooldown."""
    ctx = _make_ctx(tmp_path, cooldown=None, min_release_age=14)
    result = resolver.resolve_package_cooldown(ctx, Requirement("test-pkg"))
    assert result is not None
    assert result.min_age.days == 14


def test_per_package_cooldown_disable_via_ctx(tmp_path: pathlib.Path) -> None:
    """resolver_dist.min_release_age=0 disables cooldown for a specific package.

    Even when the global cooldown is active, a package with min_release_age=0
    in its settings should resolve the latest version.
    """
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    # Disable cooldown for test-pkg specifically.
    (settings_dir / "test-pkg.yaml").write_text(
        yaml.dump({"resolver_dist": {"min_release_age": 0}})
    )

    ctx = context.WorkContext(
        active_settings=packagesettings.Settings.from_files(
            settings_file=tmp_path / "settings.yaml",
            settings_dir=settings_dir,
            patches_dir=tmp_path / "patches",
            variant="cpu",
            max_jobs=None,
        ),
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        # With global cooldown active but per-package override=0, 2.0.0 (2 days
        # old) should be selected because the cooldown is disabled for test-pkg.
        _, version = resolver.resolve(
            ctx=ctx,
            req=Requirement("test-pkg"),
            sdist_server_url="https://pypi.org/simple/",
            include_sdists=True,
            include_wheels=True,
        )
        assert str(version) == "2.0.0"


# ---------------------------------------------------------------------------
# GitLab cooldown tests
#
# Mock data mirrors the submodlib fixture in test_resolver.py.  Tag timestamps:
#   v0.0.3  created_at: 2025-05-14T15:43:00Z  (most recent)
#   v0.0.2  tag created_at: null → falls back to commit created_at:
#             2025-04-14T14:41:32-05:00 → 2025-04-14T19:41:32Z (UTC)
#   v0.0.1  created_at: 2025-04-14T19:04:20Z
#
# bootstrap_time = 2025-05-20T00:00:00Z, cooldown = 7 days
# cutoff = 2025-05-13T00:00:00Z
#   → v0.0.3 (2025-05-14) is INSIDE  the cooldown window (blocked)
#   → v0.0.2 (2025-04-14) is OUTSIDE the cooldown window (allowed)
#   → v0.0.1 (2025-04-14) is OUTSIDE the cooldown window (allowed)
# ---------------------------------------------------------------------------

_GITLAB_BOOTSTRAP_TIME = datetime.datetime(2025, 5, 20, 0, 0, 0, tzinfo=datetime.UTC)
_GITLAB_COOLDOWN = candidate.Cooldown(
    min_age=datetime.timedelta(days=7),
    bootstrap_time=_GITLAB_BOOTSTRAP_TIME,
)

_GITLAB_API_URL = "https://gitlab.com/api/v4/projects/test%2Fpkg/repository/tags"

# Minimal GitLab tag API response with three versions at known timestamps.
_gitlab_tags_response = """
[
  {
    "name": "v0.0.3",
    "message": "",
    "target": "aaa",
    "commit": {
      "id": "aaa",
      "created_at": "2025-04-24T00:00:00.000+00:00"
    },
    "release": null,
    "protected": false,
    "created_at": "2025-05-14T15:43:00.000Z"
  },
  {
    "name": "v0.0.2",
    "message": "",
    "target": "bbb",
    "commit": {
      "id": "bbb",
      "created_at": "2025-04-14T14:41:32.000-05:00"
    },
    "release": null,
    "protected": false,
    "created_at": null
  },
  {
    "name": "v0.0.1",
    "message": "",
    "target": "ccc",
    "commit": {
      "id": "ccc",
      "created_at": "2025-04-14T19:04:20.000+00:00"
    },
    "release": null,
    "protected": false,
    "created_at": "2025-04-14T19:04:20.000Z"
  }
]
"""


def _make_gitlab_provider(
    cooldown: candidate.Cooldown | None,
) -> resolver.GitLabTagProvider:
    return resolver.GitLabTagProvider(
        project_path="test/pkg",
        server_url="https://gitlab.com",
        matcher=re.compile(r"^v(.*)$"),
        cooldown=cooldown,
        use_resolver_cache=False,
    )


def test_gitlab_cooldown_filters_recent_tag(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitLabTagProvider rejects tags published within the cooldown window."""
    monkeypatch.setattr(resolver, "DEBUG_RESOLVER", "1")
    with requests_mock.Mocker() as r:
        r.get(_GITLAB_API_URL, text=_gitlab_tags_response)
        provider = _make_gitlab_provider(_GITLAB_COOLDOWN)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())

        with caplog.at_level(logging.DEBUG, logger="fromager.resolver"):
            result = rslvr.resolve([Requirement("test-pkg")])

        candidate = result.mapping["test-pkg"]
        # v0.0.3 (2025-05-14) is inside the 7-day window; v0.0.2 is the next newest.
        assert str(candidate.version) == "0.0.2"
        assert "cooldown blocked 1 version(s): 0.0.3" in caplog.text


def test_gitlab_cooldown_disabled_selects_latest() -> None:
    """Without a cooldown, GitLabTagProvider selects the latest tag."""
    with requests_mock.Mocker() as r:
        r.get(_GITLAB_API_URL, text=_gitlab_tags_response)
        provider = _make_gitlab_provider(cooldown=None)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())
        result = rslvr.resolve([Requirement("test-pkg")])
        assert str(result.mapping["test-pkg"].version) == "0.0.3"


def test_gitlab_cooldown_no_upload_time_fails_closed(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GitLab tag with no timestamp (tag and commit created_at both null) is
    rejected fail-closed when a cooldown is active.

    GitLab structurally supports timestamps, so a missing one is treated as an
    unverifiable candidate rather than an expected absence.
    """
    monkeypatch.setattr(resolver, "DEBUG_RESOLVER", "1")
    no_timestamp_response = """
[
  {
    "name": "v1.0.0",
    "message": "",
    "target": "ddd",
    "commit": {"id": "ddd", "created_at": null},
    "release": null,
    "protected": false,
    "created_at": null
  }
]
"""
    with requests_mock.Mocker() as r:
        r.get(_GITLAB_API_URL, text=no_timestamp_response)
        provider = _make_gitlab_provider(_GITLAB_COOLDOWN)
        rslvr = resolvelib.Resolver(provider, resolvelib.BaseReporter())

        with caplog.at_level(logging.DEBUG, logger="fromager.resolver"):
            with pytest.raises(resolvelib.resolvers.ResolverException):
                rslvr.resolve([Requirement("test-pkg")])

        assert "upload_time unknown" in caplog.text


def test_github_cooldown_skips_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """GitHubTagProvider skips the cooldown with a warning rather than failing closed.

    GitHub's tag API does not return commit timestamps, so all candidates have
    upload_time=None.  Failing closed would make cooldown unusable with any
    GitHub-sourced package.  Instead, a one-time warning is emitted and the
    candidate is allowed through.
    """
    provider = resolver.GitHubTagProvider(
        organization="example",
        repo="pkg",
        cooldown=_COOLDOWN,
        use_resolver_cache=False,
    )
    candidate = resolver.Candidate(
        name="test-pkg",
        version=Version("1.0.0"),
        url="https://github.com/example/pkg/archive/v1.0.0.tar.gz",
        upload_time=None,
    )

    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        result = provider.is_blocked_by_cooldown(candidate)

    assert result is False
    assert "cooldown cannot be enforced" in caplog.text


def test_local_wheel_server_allows_without_upload_time(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """resolve_all_prebuilt_wheels() allows candidates from the local wheel server
    even when upload_time is missing, without emitting a warning.

    The local fromager wheel server is PEP 503-only and serves packages that were
    already resolved and built earlier in the same run. They are trusted and must
    not be fail-closed by the cooldown just because the local server cannot supply
    upload timestamps. Localhost indexes silently skip the cooldown check.
    """
    local_server_url = "http://127.0.0.1:9999/simple/"
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )
    ctx.wheel_server_url = local_server_url

    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": f"{local_server_url}test-pkg/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
                # no upload-time — as served by fromager's local PEP 503 server
            },
        ],
    }
    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{local_server_url}test-pkg/",
                json=no_timestamp_response,
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            results = wheels.resolve_all_prebuilt_wheels(
                ctx=ctx,
                req=Requirement("test-pkg"),
                wheel_server_urls=[local_server_url],
            )

    assert len(results) == 1
    _, version = results[0]
    assert str(version) == "1.3.2"
    assert "cooldown cannot be enforced" not in caplog.text


def test_local_wheel_server_skips_cooldown_entirely(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """resolve_cached_wheel() disables cooldown for the local wheel server.

    The local fromager wheel server serves packages that were already resolved
    and built earlier in the same run.  They are trusted, so resolve_cached_wheel
    uses PyPICacheProvider (cooldown=None) and no cooldown-related warnings are
    emitted.
    """
    local_server_url = "http://127.0.0.1:9999/simple/"
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": f"{local_server_url}test-pkg/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
            },
        ],
    }
    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{local_server_url}test-pkg/",
                json=no_timestamp_response,
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            _url, version = wheels.resolve_cached_wheel(
                ctx=ctx,
                req=Requirement("test-pkg"),
                cache_server_url=local_server_url,
            )

    assert str(version) == "1.3.2"
    assert "cooldown" not in caplog.text.lower()


def test_cache_wheel_server_skips_cooldown_entirely(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """resolve_cached_wheel() disables cooldown for the cache wheel server.

    The cache wheel server contains wheels from previous fromager runs that
    were already vetted during original sdist resolution.  Cooldown is not
    applicable.
    """
    cache_server_url = "https://registry.test/packages/pypi/simple/"
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": f"{cache_server_url}test-pkg/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
            },
        ],
    }
    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{cache_server_url}test-pkg/",
                json=no_timestamp_response,
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            _url, version = wheels.resolve_cached_wheel(
                ctx=ctx,
                req=Requirement("test-pkg"),
                cache_server_url=cache_server_url,
            )

    assert str(version) == "1.3.2"
    assert "cooldown" not in caplog.text.lower()


def test_non_cache_server_retains_cooldown(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """resolve_all_prebuilt_wheels() keeps cooldown active for non-cache servers.

    When a server URL is an external/upstream index (not local or cache),
    cooldown remains active.  Candidates without upload timestamps trigger a
    warning because the server does not support upload_time.
    """
    external_server_url = "https://external.test/simple/"
    ctx = context.WorkContext(
        active_settings=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        cooldown=_COOLDOWN,
    )

    no_timestamp_response = {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": "test_pkg-1.3.2-py3-none-any.whl",
                "url": f"{external_server_url}test-pkg/test_pkg-1.3.2-py3-none-any.whl",
                "hashes": {"sha256": "bbb"},
            },
        ],
    }
    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{external_server_url}test-pkg/",
                json=no_timestamp_response,
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            results = wheels.resolve_all_prebuilt_wheels(
                ctx=ctx,
                req=Requirement("test-pkg"),
                wheel_server_urls=[external_server_url],
            )

    assert len(results) == 1
    _, version = results[0]
    assert str(version) == "1.3.2"
    assert "cooldown cannot be enforced" in caplog.text


_LOCAL_WHEEL_SERVER = "http://127.0.0.1:8080/simple/"
_CACHE_WHEEL_SERVER = "https://cache.test/simple/"
_PACKAGE_WHEEL_SERVER = "https://custom.test/simple/"
_RECENT_UPLOAD_TIME = "2026-03-25T00:00:00+00:00"
_OLD_UPLOAD_TIME = "2026-03-15T00:00:00+00:00"


def _simple_wheel_index(
    server_url: str,
    *,
    upload_time: str | None = None,
    version: str = "1.3.2",
) -> dict[str, typing.Any]:
    filename = f"test_pkg-{version}-py3-none-any.whl"
    file_entry: dict[str, typing.Any] = {
        "filename": filename,
        "url": f"{server_url}test-pkg/{filename}",
        "hashes": {"sha256": "bbb"},
    }
    if upload_time is not None:
        file_entry["upload-time"] = upload_time
    return {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [file_entry],
    }


def _wheel_index_for_filenames(
    server_url: str, filenames: list[str]
) -> dict[str, typing.Any]:
    return {
        "meta": {"api-version": "1.1"},
        "name": "test-pkg",
        "files": [
            {
                "filename": filename,
                "url": f"{server_url}test-pkg/{filename}",
                "hashes": {"sha256": "bbb"},
            }
            for filename in filenames
        ],
    }


def _empty_index() -> dict[str, typing.Any]:
    return {"meta": {"api-version": "1.1"}, "name": "test-pkg", "files": []}


def _context_for_existing_wheel(
    tmp_path: pathlib.Path,
    *,
    package_wheel_server_url: str | None = None,
    pre_built: bool = False,
) -> context.WorkContext:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    if package_wheel_server_url is not None or pre_built:
        variant_lines = ["variants:", "  cpu:"]
        if pre_built:
            variant_lines.append("    pre_built: true")
        if package_wheel_server_url is not None:
            variant_lines.append(f"    wheel_server_url: {package_wheel_server_url}")
        (settings_dir / "test-pkg.yaml").write_text(
            "\n".join(variant_lines) + "\n",
            encoding="utf-8",
        )
    settings = packagesettings.Settings.from_files(
        settings_file=tmp_path / "settings.yaml",
        settings_dir=settings_dir,
        variant="cpu",
        patches_dir=tmp_path / "patches",
        max_jobs=None,
    )
    return context.WorkContext(
        active_settings=settings,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url=_LOCAL_WHEEL_SERVER,
        cooldown=_COOLDOWN,
    )


def _record_download(
    seen: list[str],
) -> typing.Callable[[Requirement, str, pathlib.Path], pathlib.Path]:
    def _download(
        req: Requirement,
        wheel_url: str,
        output_directory: pathlib.Path,
    ) -> pathlib.Path:
        del req
        seen.append(wheel_url)
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / wheel_url.rsplit("/", 1)[-1]
        path.write_bytes(b"")
        return path

    return _download


def _set_existing_wheel_build_tag_hook(
    ctx: context.WorkContext, suffixes: list[str]
) -> None:
    """Configure a hook and changelog for build-tag lookup tests."""

    def hook(**kwargs: object) -> list[str]:
        return suffixes

    ctx.settings._settings = ctx.settings._settings.model_copy(
        update={
            "changelog": {"cpu": ["test entry"]},
            "wheels": WheelSettings(build_tag_hook=hook),
        }
    )
    ctx.settings._pbi_cache.clear()


def test_is_wheel_built_checks_all_candidates(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched candidate does not hide a later match on the same server."""
    ctx = _context_for_existing_wheel(tmp_path)
    _set_existing_wheel_build_tag_hook(ctx, ["aaa"])

    version = Version("1.3.2")
    stale_name = "test_pkg-1.3.2-1_zzz-py3-none-any.whl"
    matching_name = "test_pkg-1.3.2-1_aaa-py3-none-any.whl"
    matching_url = f"{_LOCAL_WHEEL_SERVER}test-pkg/{matching_name}"

    downloaded: list[str] = []
    monkeypatch.setattr(
        build_command.wheels, "download_wheel", _record_download(downloaded)
    )

    with requests_mock.Mocker() as r:
        r.get(
            f"{_LOCAL_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(
                _LOCAL_WHEEL_SERVER, [stale_name, matching_name]
            ),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        found = build_command._is_wheel_built(ctx, "test-pkg", version)

    assert found is not None
    assert found.name == matching_name
    assert downloaded == [matching_url]
    assert [request.url for request in r.request_history] == [
        f"{_LOCAL_WHEEL_SERVER}test-pkg/"
    ]


def test_is_wheel_built_checks_next_server_after_tag_mismatch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatch on the local server does not hide a match in the job cache."""
    ctx = _context_for_existing_wheel(tmp_path)
    _set_existing_wheel_build_tag_hook(ctx, ["aaa"])

    version = Version("1.3.2")
    stale_name = "test_pkg-1.3.2-1_zzz-py3-none-any.whl"
    matching_name = "test_pkg-1.3.2-1_aaa-py3-none-any.whl"
    matching_url = f"{_CACHE_WHEEL_SERVER}test-pkg/{matching_name}"
    downloaded: list[str] = []
    monkeypatch.setattr(
        build_command.wheels, "download_wheel", _record_download(downloaded)
    )

    with requests_mock.Mocker() as r:
        r.get(
            f"{_LOCAL_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(_LOCAL_WHEEL_SERVER, [stale_name]),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        r.get(
            f"{_CACHE_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(_CACHE_WHEEL_SERVER, [matching_name]),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        found = build_command._is_wheel_built(
            ctx,
            "test-pkg",
            version,
            cache_wheel_server_url=_CACHE_WHEEL_SERVER,
        )

    assert found is not None
    assert found.name == matching_name
    assert [request.url for request in r.request_history] == [
        f"{_LOCAL_WHEEL_SERVER}test-pkg/",
        f"{_CACHE_WHEEL_SERVER}test-pkg/",
    ]
    assert downloaded == [matching_url]


def test_is_wheel_built_propagates_build_tag_hook_error(
    tmp_path: pathlib.Path,
) -> None:
    """Invalid hook output is not treated as a cache miss."""
    ctx = _context_for_existing_wheel(tmp_path)
    _set_existing_wheel_build_tag_hook(ctx, ["invalid-suffix"])
    version = Version("1.3.2")
    filename = "test_pkg-1.3.2-1_aaa-py3-none-any.whl"

    with requests_mock.Mocker() as r:
        r.get(
            f"{_LOCAL_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(_LOCAL_WHEEL_SERVER, [filename]),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        with pytest.raises(ValueError, match="invalid segment"):
            build_command._is_wheel_built(ctx, "test-pkg", version)


def test_is_wheel_built_propagates_inconsistent_build_tag(
    tmp_path: pathlib.Path,
) -> None:
    """A higher build number with the expected suffix remains an error."""
    ctx = _context_for_existing_wheel(tmp_path)
    _set_existing_wheel_build_tag_hook(ctx, ["aaa"])
    version = Version("1.3.2")
    filename = "test_pkg-1.3.2-2_aaa-py3-none-any.whl"

    with requests_mock.Mocker() as r:
        r.get(
            f"{_LOCAL_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(_LOCAL_WHEEL_SERVER, [filename]),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        with pytest.raises(ValueError, match=r"changelog.*inconsistent"):
            build_command._is_wheel_built(ctx, "test-pkg", version)


def test_is_wheel_built_prebuilt_keeps_publisher_build_tag(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-built wheel with a publisher build number is reused.

    The changelog tag is empty for pre-built packages. That must not reject
    a higher build number, and the highest published build number is used.
    """
    ctx = _context_for_existing_wheel(
        tmp_path,
        package_wheel_server_url=_PACKAGE_WHEEL_SERVER,
        pre_built=True,
    )
    version = Version("1.3.2")
    older_name = "test_pkg-1.3.2-1-py3-none-any.whl"
    newer_name = "test_pkg-1.3.2-2-py3-none-any.whl"
    newer_url = f"{_PACKAGE_WHEEL_SERVER}test-pkg/{newer_name}"
    downloaded: list[str] = []
    monkeypatch.setattr(
        build_command.wheels, "download_wheel", _record_download(downloaded)
    )

    with requests_mock.Mocker() as r:
        r.get(
            f"{_PACKAGE_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(
                _PACKAGE_WHEEL_SERVER, [older_name, newer_name]
            ),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        found = build_command._is_wheel_built(ctx, "test-pkg", version)

    assert found is not None
    assert found.name == newer_name
    assert downloaded == [newer_url]


def test_is_wheel_built_prebuilt_reuses_cache_build_tag(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-built package reuses a build-tagged wheel from the job cache.

    No package wheel_server_url is set, so the lookup uses the local server
    and --cache-wheel-server-url. The publisher build number must not raise.
    """
    ctx = _context_for_existing_wheel(tmp_path, pre_built=True)
    version = Version("1.3.2")
    wheel_name = "test_pkg-1.3.2-2-py3-none-any.whl"
    wheel_url = f"{_CACHE_WHEEL_SERVER}test-pkg/{wheel_name}"
    downloaded: list[str] = []
    monkeypatch.setattr(
        build_command.wheels, "download_wheel", _record_download(downloaded)
    )

    with requests_mock.Mocker() as r:
        r.get(
            f"{_LOCAL_WHEEL_SERVER}test-pkg/",
            json=_empty_index(),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        r.get(
            f"{_CACHE_WHEEL_SERVER}test-pkg/",
            json=_wheel_index_for_filenames(_CACHE_WHEEL_SERVER, [wheel_name]),
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        found = build_command._is_wheel_built(
            ctx,
            "test-pkg",
            version,
            cache_wheel_server_url=_CACHE_WHEEL_SERVER,
        )

    assert found is not None
    assert found.name == wheel_name
    assert downloaded == [wheel_url]
    assert [request.url for request in r.request_history] == [
        f"{_LOCAL_WHEEL_SERVER}test-pkg/",
        f"{_CACHE_WHEEL_SERVER}test-pkg/",
    ]


def test_is_wheel_built_uses_package_wheel_server_url(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A package wheel_server_url is the only index consulted.

    The job cache and local server are not fallbacks. A missing upload
    timestamp warns and still allows the wheel, because this path uses the
    pre-built resolver rather than the trusted cache.
    """
    ctx = _context_for_existing_wheel(
        tmp_path,
        package_wheel_server_url=_PACKAGE_WHEEL_SERVER,
    )
    seen: list[str] = []
    monkeypatch.setattr(build_command.wheels, "download_wheel", _record_download(seen))

    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{_PACKAGE_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(_PACKAGE_WHEEL_SERVER),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            r.get(
                f"{_CACHE_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(
                    _CACHE_WHEEL_SERVER,
                    upload_time=_OLD_UPLOAD_TIME,
                ),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            r.get(
                f"{_LOCAL_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(_LOCAL_WHEEL_SERVER),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            found = build_command._is_wheel_built(
                ctx,
                "test-pkg",
                Version("1.3.2"),
                cache_wheel_server_url=_CACHE_WHEEL_SERVER,
            )

    assert found is not None
    assert found.name == "test_pkg-1.3.2-py3-none-any.whl"
    assert seen == [f"{_PACKAGE_WHEEL_SERVER}test-pkg/test_pkg-1.3.2-py3-none-any.whl"]
    requested = [request.url for request in r.request_history]
    assert any(url.startswith(_PACKAGE_WHEEL_SERVER) for url in requested)
    assert all(not url.startswith(_CACHE_WHEEL_SERVER) for url in requested)
    assert all(not url.startswith(_LOCAL_WHEEL_SERVER) for url in requested)
    assert "cooldown cannot be enforced" in caplog.text


def test_is_wheel_built_package_wheel_server_keeps_cooldown(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A too-new wheel on a package index is rejected and the cache is not used.

    The cache holds an older matching wheel. Falling through to it would hide
    the cooldown that must stay on for an upstream pre-built index.
    """
    ctx = _context_for_existing_wheel(
        tmp_path,
        package_wheel_server_url=_PACKAGE_WHEEL_SERVER,
    )
    seen: list[str] = []
    monkeypatch.setattr(build_command.wheels, "download_wheel", _record_download(seen))

    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{_PACKAGE_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(
                    _PACKAGE_WHEEL_SERVER,
                    upload_time=_RECENT_UPLOAD_TIME,
                ),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            r.get(
                f"{_CACHE_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(
                    _CACHE_WHEEL_SERVER,
                    upload_time=_OLD_UPLOAD_TIME,
                ),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            r.get(
                f"{_LOCAL_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(
                    _LOCAL_WHEEL_SERVER,
                    upload_time=_OLD_UPLOAD_TIME,
                ),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            found = build_command._is_wheel_built(
                ctx,
                "test-pkg",
                Version("1.3.2"),
                cache_wheel_server_url=_CACHE_WHEEL_SERVER,
            )

    assert found is None
    assert seen == []
    requested = [request.url for request in r.request_history]
    assert any(url.startswith(_PACKAGE_WHEEL_SERVER) for url in requested)
    assert all(not url.startswith(_CACHE_WHEEL_SERVER) for url in requested)
    assert all(not url.startswith(_LOCAL_WHEEL_SERVER) for url in requested)
    assert "cooldown blocked" in caplog.text


def test_is_wheel_built_cache_ignores_recent_upload_time(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The job cache is trusted even when its upload-time is inside the cooldown.

    Pulp reports the time the artifact was added to the index, not the PyPI
    publish date. That timestamp must not cause a cached wheel to be rebuilt.
    """
    ctx = _context_for_existing_wheel(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(build_command.wheels, "download_wheel", _record_download(seen))

    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        with requests_mock.Mocker() as r:
            r.get(
                f"{_LOCAL_WHEEL_SERVER}test-pkg/",
                json=_empty_index(),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            r.get(
                f"{_CACHE_WHEEL_SERVER}test-pkg/",
                json=_simple_wheel_index(
                    _CACHE_WHEEL_SERVER,
                    upload_time=_RECENT_UPLOAD_TIME,
                ),
                headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
            )
            found = build_command._is_wheel_built(
                ctx,
                "test-pkg",
                Version("1.3.2"),
                cache_wheel_server_url=_CACHE_WHEEL_SERVER,
            )

    assert found is not None
    assert seen == [f"{_CACHE_WHEEL_SERVER}test-pkg/test_pkg-1.3.2-py3-none-any.whl"]
    assert "cooldown" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# max-release-age tests
# ---------------------------------------------------------------------------

# Uses the same _cooldown_json_response fixture:
#   2.0.0  uploaded 2026-03-24 →  2 days old
#   1.3.2  uploaded 2026-03-15 → 11 days old
#   1.2.2  uploaded 2026-01-01 → 84 days old
# _BOOTSTRAP_TIME = 2026-03-26

# max_age_cutoff = bootstrap_time - max_release_age
# With 30 days: cutoff = 2026-02-24 → keeps 2.0.0 and 1.3.2, filters 1.2.2
# With 5 days:  cutoff = 2026-03-21 → keeps only 2.0.0


def test_max_release_age_filters_old_versions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Versions older than max-release-age are filtered out."""
    max_age_cutoff = _BOOTSTRAP_TIME - datetime.timedelta(days=30)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider, Requirement("test-pkg"), max_age_cutoff=max_age_cutoff
            )

    versions = [str(v) for _, v in results]
    assert "2.0.0" in versions
    assert "1.3.2" in versions
    assert "1.2.2" not in versions
    assert "found 3 candidate(s)" in caplog.text
    assert "have 2 candidate(s)" in caplog.text
    assert "published within" in caplog.text


def test_max_release_age_keeps_only_recent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With a tight max-release-age, only very recent versions survive."""
    max_age_cutoff = _BOOTSTRAP_TIME - datetime.timedelta(days=5)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider, Requirement("test-pkg"), max_age_cutoff=max_age_cutoff
            )

    versions = [str(v) for _, v in results]
    assert versions == ["2.0.0"]
    assert "found 3 candidate(s)" in caplog.text
    assert "have 1 candidate(s)" in caplog.text
    assert "published within" in caplog.text


def test_max_release_age_disabled_returns_all() -> None:
    """When max_age_cutoff is None, all versions are returned."""
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        results = resolver.find_all_matching_from_provider(
            provider, Requirement("test-pkg"), max_age_cutoff=None
        )

    versions = [str(v) for _, v in results]
    assert "2.0.0" in versions
    assert "1.3.2" in versions
    assert "1.2.2" in versions


def test_max_release_age_all_too_old_keeps_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When all versions are older than cutoff, keep all candidates and warn."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider, Requirement("test-pkg"), max_age_cutoff=max_age_cutoff
            )
    versions = [str(v) for _, v in results]
    assert versions == ["2.0.0", "1.3.2", "1.2.2"]
    assert "keeping all to avoid empty resolution" in caplog.text


def test_max_release_age_all_too_old_returns_empty_when_fallback_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With AgeFallback.NONE and all versions too old, return empty list."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NONE,
            )
    assert results == []
    assert "all 3 candidate(s)" in caplog.text
    assert "keeping all to avoid empty resolution" not in caplog.text


def test_max_release_age_falls_back_to_newest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With AgeFallback.NEWEST and all versions too old, return only the newest."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NEWEST,
            )
    versions = [str(v) for _, v in results]
    assert versions == ["2.0.0"]
    assert "falling back to newest version 2.0.0" in caplog.text
    assert "keeping all to avoid empty resolution" not in caplog.text


def test_max_release_age_candidates_without_upload_time_pass_through() -> None:
    """Candidates without upload_time are not filtered out by max-release-age."""
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
    max_age_cutoff = _BOOTSTRAP_TIME - datetime.timedelta(days=5)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=no_timestamp_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        results = resolver.find_all_matching_from_provider(
            provider, Requirement("test-pkg"), max_age_cutoff=max_age_cutoff
        )

    assert len(results) == 1
    assert str(results[0][1]) == "1.0.0"


def test_max_release_age_combined_with_cooldown() -> None:
    """Both cooldown (min-release-age) and max-release-age work together as a window."""
    max_age_cutoff = _BOOTSTRAP_TIME - datetime.timedelta(days=30)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        # Cooldown blocks 2.0.0 (too new), max-release-age blocks 1.2.2 (too old)
        provider = resolver.PyPIProvider(include_sdists=True, cooldown=_COOLDOWN)
        results = resolver.find_all_matching_from_provider(
            provider, Requirement("test-pkg"), max_age_cutoff=max_age_cutoff
        )

    versions = [str(v) for _, v in results]
    assert versions == ["1.3.2"]


def test_compute_max_age_cutoff_with_cooldown(
    tmp_context: context.WorkContext,
) -> None:
    """_compute_max_age_cutoff uses cooldown's bootstrap_time when available."""
    tmp_context.cooldown = candidate.Cooldown(
        min_age=datetime.timedelta(days=7),
        bootstrap_time=_BOOTSTRAP_TIME,
    )
    tmp_context.set_max_release_age(30)
    cutoff = resolver._compute_max_age_cutoff(tmp_context)
    assert cutoff == _BOOTSTRAP_TIME - datetime.timedelta(days=30)


def test_compute_max_age_cutoff_without_cooldown(
    tmp_context: context.WorkContext,
) -> None:
    """_compute_max_age_cutoff uses current time when no cooldown is set."""
    tmp_context.cooldown = None
    tmp_context.set_max_release_age(30)
    cutoff = resolver._compute_max_age_cutoff(tmp_context)
    assert cutoff is not None
    expected = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
    assert abs((cutoff - expected).total_seconds()) < 2


def test_compute_max_age_cutoff_disabled(
    tmp_context: context.WorkContext,
) -> None:
    """_compute_max_age_cutoff returns None when max_release_age is not set."""
    cutoff = resolver._compute_max_age_cutoff(tmp_context)
    assert cutoff is None


def test_resolve_package_cooldown_exempt_toplevel_equality_pin(
    tmp_path: pathlib.Path,
) -> None:
    """Top-level == pin bypasses cooldown."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg==1.3.2"), req_type=RequirementType.TOP_LEVEL
    )
    assert result is None


def test_resolve_package_cooldown_enforced_transitive_equality_pin(
    tmp_path: pathlib.Path,
) -> None:
    """Transitive == pin does NOT bypass cooldown."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg==1.3.2"), req_type=RequirementType.INSTALL
    )
    assert result is _COOLDOWN


def test_resolve_package_cooldown_enforced_toplevel_no_pin(
    tmp_path: pathlib.Path,
) -> None:
    """Top-level requirement without == still gets cooldown."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg>=1.0"), req_type=RequirementType.TOP_LEVEL
    )
    assert result is _COOLDOWN


def test_resolve_package_cooldown_none_req_type_not_exempt(
    tmp_path: pathlib.Path,
) -> None:
    """Unknown req_type (None) with == does NOT bypass cooldown."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg==1.3.2"), req_type=None
    )
    assert result is _COOLDOWN


def test_resolve_package_cooldown_toplevel_wildcard_equality_not_exempt(
    tmp_path: pathlib.Path,
) -> None:
    """Top-level wildcard equality (==1.*) is not an exact pin — cooldown applies."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg==1.*"), req_type=RequirementType.TOP_LEVEL
    )
    assert result is _COOLDOWN


def test_resolve_package_cooldown_toplevel_compound_specifier_not_exempt(
    tmp_path: pathlib.Path,
) -> None:
    """Top-level compound specifier (==1.0,>0.9) is not a single exact pin."""
    ctx = _make_ctx(tmp_path, cooldown=_COOLDOWN)
    result = resolver.resolve_package_cooldown(
        ctx, Requirement("test-pkg==1.0,>0.9"), req_type=RequirementType.TOP_LEVEL
    )
    assert result is _COOLDOWN


# ---------------------------------------------------------------------------
# constraint pin bypass tests — exact == pins skip age filtering
# ---------------------------------------------------------------------------


def test_max_release_age_skips_filter_for_pinned_constraint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exact == pin in constraints bypasses age filtering."""
    # Cutoff in the future so ALL versions are "too old"
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    c = constraints.Constraints()
    c.add_constraint("test-pkg==1.2.2")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, constraints=c)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NONE,
            )

    # The pin restricts candidates to 1.2.2, and age filtering is
    # bypassed — so 1.2.2 must survive even though it's outside the window.
    versions = [str(v) for _, v in results]
    assert "1.2.2" in versions
    assert "skipping age filter for pinned constraint" in caplog.text
    assert "keeping all to avoid empty resolution" not in caplog.text


def test_max_release_age_skips_filter_for_pinned_constraint_with_newest_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exact == pin bypasses age filtering even with NEWEST fallback."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    c = constraints.Constraints()
    c.add_constraint("test-pkg==1.2.2")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, constraints=c)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NEWEST,
            )

    versions = [str(v) for _, v in results]
    assert "1.2.2" in versions
    assert "skipping age filter for pinned constraint" in caplog.text
    assert "falling back to newest version" not in caplog.text


def test_max_release_age_still_filters_range_constrained_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Range constraints (not exact pins) are still subject to age filtering."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    c = constraints.Constraints()
    c.add_constraint("test-pkg>=1.0")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True, constraints=c)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NONE,
            )

    assert results == []
    assert "skipping age filter for pinned constraint" not in caplog.text


def test_max_release_age_still_filters_unconstrained_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unconstrained packages are still subject to age filtering."""
    max_age_cutoff = _BOOTSTRAP_TIME + datetime.timedelta(days=1)
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/test-pkg/",
            json=_cooldown_json_response,
            headers={"Content-Type": _PYPI_SIMPLE_JSON_CONTENT_TYPE},
        )
        provider = resolver.PyPIProvider(include_sdists=True)
        with caplog.at_level(logging.INFO, logger="fromager.resolver"):
            results = resolver.find_all_matching_from_provider(
                provider,
                Requirement("test-pkg"),
                max_age_cutoff=max_age_cutoff,
                age_fallback=resolver.AgeFallback.NONE,
            )

    assert results == []
    assert "skipping age filter for pinned constraint" not in caplog.text
