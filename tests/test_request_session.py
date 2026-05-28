from __future__ import annotations

import os
from collections.abc import Generator, MutableMapping
from unittest.mock import MagicMock, patch

import pytest
import requests

from fromager.request_session import (
    SessionAuth,
    _resolve_github_auth,
    _resolve_gitlab_auth,
    create_session,
)


@pytest.fixture
def mock_environ() -> Generator[MutableMapping[str, str]]:
    """Patch os.environ with an empty dict and return it."""
    with patch.dict(os.environ, {}, clear=True):
        yield os.environ


@pytest.fixture
def mock_netrc() -> Generator[MagicMock]:
    """Patch get_netrc_auth to return None and return the mock."""
    with patch("fromager.request_session.get_netrc_auth", return_value=None) as m:
        yield m


def _make_request(url: str) -> requests.PreparedRequest:
    return requests.Request("GET", url).prepare()


def test_session_auth() -> None:
    """Dispatch, caching, cache invalidation, and scheme separation."""
    call_count = 0

    def counting(scheme: str, hostname: str) -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        return {"X-Token": "val"}

    auth = SessionAuth()
    auth.add("https://api.test", counting)

    # get() resolves and caches, second call uses cache
    assert auth.get("https://api.test/path") == {"X-Token": "val"}
    assert auth.get("https://api.test/other") == {"X-Token": "val"}
    assert call_count == 1

    # __call__ uses the same cache
    r = _make_request("https://api.test/path")
    auth(r)
    assert r.headers["X-Token"] == "val"
    assert call_count == 1

    # No match -> empty dict from get(), no header from __call__
    assert auth.get("https://other.test/") == {}
    r2 = _make_request("https://other.test/")
    auth(r2)
    assert "X-Token" not in r2.headers

    # Re-add invalidates cache
    auth.add("https://api.test", lambda s, h: {"X-Token": "new"})
    assert auth.get("https://api.test/") == {"X-Token": "new"}

    # http vs https are separate
    auth.add("http://api.test", lambda s, h: {"X-Token": "http"})
    assert auth.get("http://api.test/") == {"X-Token": "http"}
    assert auth.get("https://api.test/") == {"X-Token": "new"}


def test_session_auth_add_validation() -> None:
    auth = SessionAuth()
    with pytest.raises(ValueError, match="Unsupported scheme"):
        auth.add("ftp://host.test", lambda s, h: {})
    with pytest.raises(ValueError, match="Missing hostname"):
        auth.add("https://", lambda s, h: {})


def test_resolve_github_auth(
    mock_environ: MutableMapping[str, str], mock_netrc: MagicMock
) -> None:
    """Netrc > GITHUB_TOKEN > empty."""
    assert _resolve_github_auth("https", "api.github.com") == {}

    mock_environ["GITHUB_TOKEN"] = "env-token"
    assert _resolve_github_auth("https", "api.github.com") == {
        "Authorization": "token env-token"
    }

    mock_netrc.return_value = ("user", "netrc-token")
    assert _resolve_github_auth("https", "api.github.com") == {
        "Authorization": "token netrc-token"
    }


def test_resolve_gitlab_auth(
    mock_environ: MutableMapping[str, str], mock_netrc: MagicMock
) -> None:
    """Netrc > CI_JOB_TOKEN > GITLAB_PRIVATE_TOKEN > empty."""
    assert _resolve_gitlab_auth("https", "gitlab.com") == {}

    mock_environ["GITLAB_PRIVATE_TOKEN"] = "priv"
    assert _resolve_gitlab_auth("https", "gitlab.com") == {"PRIVATE-TOKEN": "priv"}

    mock_environ["CI_JOB_TOKEN"] = "ci"
    assert _resolve_gitlab_auth("https", "gitlab.com") == {"JOB-TOKEN": "ci"}

    # Netrc with regular user -> PRIVATE-TOKEN
    mock_netrc.return_value = ("myuser", "netrc-token")
    assert _resolve_gitlab_auth("https", "gitlab.com") == {
        "PRIVATE-TOKEN": "netrc-token"
    }

    # Netrc with gitlab-ci-token login -> JOB-TOKEN
    mock_netrc.return_value = ("gitlab-ci-token", "job-secret")
    assert _resolve_gitlab_auth("https", "gitlab.com") == {"JOB-TOKEN": "job-secret"}


def test_create_session(
    mock_environ: MutableMapping[str, str], mock_netrc: MagicMock
) -> None:
    s, auth = create_session()

    assert isinstance(s, requests.Session)
    assert s.auth is auth
    assert ("https", "api.github.com") in auth._callbacks
    assert ("https", "gitlab.com") in auth._callbacks
