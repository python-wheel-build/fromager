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
from collections import defaultdict

import pytest
import requests_mock
import resolvelib
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver, sources
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
    """ctx.cooldown propagates through resolver.resolve() to any provider.

    Cooldown is set on the provider by resolve() after find_and_invoke()
    returns it, so plugin authors do not need to handle cooldown themselves.
    """
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
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


def test_cooldown_applied_via_get_source_provider(tmp_path: pathlib.Path) -> None:
    """ctx.cooldown propagates through sources.get_source_provider() to any provider.

    The bootstrapper resolves sources via get_source_provider(), not resolver.resolve().
    This test ensures cooldown is applied on that path too, so plugin-provided
    providers cannot silently bypass the cooldown.
    """
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
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


def test_wheel_only_resolution_ignores_cooldown_without_upload_time(
    tmp_path: pathlib.Path,
) -> None:
    """resolve() with include_sdists=False suppresses cooldown for wheel-only lookups.

    Cache servers and prebuilt wheel servers (fromager wheel-server, Pulp,
    GitLab package registry) serve Simple HTML v1.0 with no upload_time.
    Cooldown only applies to sdist resolution from a public index; wheel-only
    lookups use a different trust model and must never fail-closed against
    servers that structurally cannot provide timestamps.
    """
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
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
        _, version = resolver.resolve(
            ctx=ctx,
            req=Requirement("test-pkg==1.3.2"),
            sdist_server_url="https://cache.example.com/simple/",
            include_sdists=False,
            include_wheels=True,
        )
        assert str(version) == "1.3.2"


def test_resolve_package_cooldown_inherits_global() -> None:
    """None per-package override returns the global cooldown unchanged."""
    result = resolver.resolve_package_cooldown(_COOLDOWN, None)
    assert result is _COOLDOWN


def test_resolve_package_cooldown_disabled_per_package() -> None:
    """per_package_days=0 disables the cooldown for the package even when global is set."""
    result = resolver.resolve_package_cooldown(_COOLDOWN, 0)
    assert result is None


def test_resolve_package_cooldown_disabled_no_global() -> None:
    """per_package_days=0 with no global cooldown still returns None."""
    result = resolver.resolve_package_cooldown(None, 0)
    assert result is None


def test_resolve_package_cooldown_override_days() -> None:
    """Positive per-package override creates a new Cooldown with the given days."""
    result = resolver.resolve_package_cooldown(_COOLDOWN, 30)
    assert result is not None
    assert result.min_age.days == 30
    # bootstrap_time is inherited from the global cooldown for a consistent cutoff.
    assert result.bootstrap_time == _COOLDOWN.bootstrap_time


def test_resolve_package_cooldown_override_no_global() -> None:
    """Positive per-package override works even without a global cooldown."""
    result = resolver.resolve_package_cooldown(None, 14)
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
        constraints_file=None,
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
_GITLAB_COOLDOWN = Cooldown(
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


def _make_gitlab_provider(cooldown: Cooldown | None) -> resolver.GitLabTagProvider:
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
        assert "skipping 0.0.3" in caplog.text
        assert "cooldown" in caplog.text


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
    req = Requirement("test-pkg")
    requirements: typing.Any = defaultdict(list)
    requirements["test-pkg"].append(req)
    incompatibilities: typing.Any = defaultdict(list)

    with caplog.at_level(logging.WARNING, logger="fromager.resolver"):
        result = provider.validate_candidate(
            "test-pkg", requirements, incompatibilities, candidate
        )

    assert result is True
    assert "cooldown cannot be enforced" in caplog.text
    assert "not yet implemented" in caplog.text
