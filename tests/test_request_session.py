from __future__ import annotations

import netrc
import os
import pathlib
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


@pytest.fixture(autouse=True)
def netrc_path(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Isolate netrc lookup from the user's credentials."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("NETRC", raising=False)
    path = tmp_path / ".netrc"
    path.touch(mode=0o600)
    return path


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


@pytest.mark.parametrize("netrc_location", ["home", "windows", "environment"])
def test_session_uses_netrc_for_unregistered_host(
    netrc_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    netrc_location: str,
) -> None:
    """Prepare wheel-index requests with Basic auth from each netrc location."""
    if netrc_location == "windows":
        netrc_path = netrc_path.rename(netrc_path.with_name("_netrc"))
    path = (
        netrc_path.with_name("credentials")
        if netrc_location == "environment"
        else netrc_path
    )
    path.touch(mode=0o600)
    path.write_text("machine wheels.test login reader password secret\n")
    if netrc_location == "environment":
        netrc_path.write_text("machine wheels.test login wrong password credentials\n")
        monkeypatch.setenv("NETRC", str(path))
    session, _ = create_session()

    request = session.prepare_request(
        requests.Request("GET", "https://wheels.test/simple/banks/")
    )
    other_host = session.prepare_request(
        requests.Request("GET", "https://other.test/simple/")
    )

    assert request.headers["Authorization"] == "Basic cmVhZGVyOnNlY3JldA=="
    assert "Authorization" not in other_host.headers


def test_session_without_netrc_credentials(netrc_path: pathlib.Path) -> None:
    """Leave an unregistered host unauthenticated when netrc has no match."""
    netrc_path.write_text("machine other.test login reader password secret\n")
    session, _ = create_session()

    request = session.prepare_request(
        requests.Request("GET", "https://wheels.test/simple/")
    )

    assert "Authorization" not in request.headers


@pytest.mark.parametrize(
    "url,username,expected_headers",
    [
        ("https://api.github.com/repos", "reader", {"Authorization": "token secret"}),
        ("https://gitlab.com/api/v4", "reader", {"PRIVATE-TOKEN": "secret"}),
        ("https://gitlab.com/api/v4", "gitlab-ci-token", {"JOB-TOKEN": "secret"}),
    ],
)
def test_session_preserves_registered_auth(
    mock_netrc: MagicMock,
    url: str,
    username: str,
    expected_headers: dict[str, str],
) -> None:
    """Keep GitHub and GitLab token headers instead of applying Basic auth."""
    mock_netrc.return_value = (username, "secret")
    session, _ = create_session()

    request = session.prepare_request(requests.Request("GET", url))

    for name, value in expected_headers.items():
        assert request.headers[name] == value
    if "Authorization" not in expected_headers:
        assert "Authorization" not in request.headers


def test_session_preserves_empty_registered_auth(netrc_path: pathlib.Path) -> None:
    """Do not apply fallback credentials to a host with a registered callback."""
    netrc_path.write_text("machine wheels.test login reader password secret\n")
    session, auth = create_session()
    auth.add("https://wheels.test", lambda scheme, hostname: {})

    request = session.prepare_request(
        requests.Request("GET", "https://wheels.test/simple/")
    )

    assert "Authorization" not in request.headers


def test_session_preserves_authorization_header(netrc_path: pathlib.Path) -> None:
    """Do not overwrite an explicit bearer token with netrc credentials."""
    netrc_path.write_text("machine wheels.test login reader password secret\n")
    session, _ = create_session()

    request = session.prepare_request(
        requests.Request(
            "GET",
            "https://wheels.test/simple/",
            headers={"Authorization": "Bearer token"},
        )
    )

    assert request.headers["Authorization"] == "Bearer token"


def test_session_preserves_request_auth(netrc_path: pathlib.Path) -> None:
    """Request-specific authentication overrides the session handler."""
    netrc_path.write_text("machine wheels.test login reader password secret\n")
    session, _ = create_session()

    request = session.prepare_request(
        requests.Request(
            "GET", "https://wheels.test/simple/", auth=("explicit", "token")
        )
    )

    assert request.headers["Authorization"] == "Basic ZXhwbGljaXQ6dG9rZW4="


@pytest.mark.parametrize(
    "contents,url",
    [
        ("default login reader password secret\n", "https://wheels.test/"),
        ("default login reader password secret\n", "https://default/"),
        ("machine wheels.test login reader password secret\n", "http://wheels.test/"),
        ("machine wheels.test\n", "https://wheels.test/"),
        ("machine other.test login reader password secret\n", "https://wheels.test/"),
        ("machine wheels.test unexpected secret\n", "https://wheels.test/"),
    ],
)
def test_session_ignores_ineligible_netrc_credentials(
    netrc_path: pathlib.Path, contents: str, url: str
) -> None:
    """Only exact, nonempty machine entries over HTTPS supply credentials."""
    netrc_path.write_text(contents)
    session, _ = create_session()

    request = session.prepare_request(requests.Request("GET", url))

    assert "Authorization" not in request.headers


@pytest.mark.parametrize(
    "contents", ["", "machine wheels.test login reader password secret\n"]
)
@patch("fromager.request_session.netrc.netrc", wraps=netrc.netrc)
def test_session_caches_netrc_per_host(
    parse_netrc: MagicMock, netrc_path: pathlib.Path, contents: str
) -> None:
    """Cache successful and empty lookups until a host callback is registered."""
    netrc_path.write_text(contents)
    session, auth = create_session()
    first = session.prepare_request(requests.Request("GET", "https://wheels.test/"))
    netrc_path.write_text("machine wheels.test login changed password credentials\n")

    second = session.prepare_request(
        requests.Request("GET", "https://wheels.test/other")
    )

    assert second.headers.get("Authorization") == first.headers.get("Authorization")
    assert auth.get("https://wheels.test/") == (
        {"Authorization": "Basic cmVhZGVyOnNlY3JldA=="} if contents else {}
    )
    assert parse_netrc.call_count == 1
    auth.add("https://wheels.test", lambda scheme, hostname: {})
    opted_out = session.prepare_request(requests.Request("GET", "https://wheels.test/"))
    assert "Authorization" not in opted_out.headers


def test_session_preserves_headers_for_registered_host() -> None:
    """Explicit headers take precedence over registered callback headers."""
    session, auth = create_session()
    auth.add(
        "https://wheels.test",
        lambda scheme, hostname: {"Authorization": "token resolved"},
    )

    request = session.prepare_request(
        requests.Request(
            "GET", "https://wheels.test/", headers={"authorization": "Bearer explicit"}
        )
    )

    assert request.headers["Authorization"] == "Bearer explicit"


def test_session_auth_supports_custom_fallback() -> None:
    """Use the fallback for unregistered hosts and allow host-specific opt-out."""
    auth = SessionAuth(fallback=lambda scheme, hostname: {"X-Host": hostname})

    assert auth.get("https://wheels.test/") == {"X-Host": "wheels.test"}
    auth.add("https://wheels.test", lambda scheme, hostname: {})
    assert auth.get("https://wheels.test/") == {}


@pytest.mark.parametrize("location", ["missing", "directory"])
def test_session_handles_unreadable_netrc(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    """Missing or unreadable netrc files leave the request unauthenticated."""
    path = tmp_path / location if location == "missing" else tmp_path
    monkeypatch.setenv("NETRC", str(path))
    session, _ = create_session()

    request = session.prepare_request(requests.Request("GET", "https://wheels.test/"))

    assert "Authorization" not in request.headers


def test_session_does_not_log_malformed_netrc_credentials(
    netrc_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed netrc errors must not expose credential text in logs."""
    netrc_path.write_text(
        "machine wheels.test login reader password secret sensitive-token\n"
    )
    session, _ = create_session()

    request = session.prepare_request(requests.Request("GET", "https://wheels.test/"))

    assert "Authorization" not in request.headers
    assert "cannot read credentials" in caplog.text
    assert "secret" not in caplog.text
    assert "sensitive-token" not in caplog.text


@pytest.mark.parametrize(
    "entry,expected",
    [
        (
            "machine wheels.test account reader password secret\n",
            "Basic cmVhZGVyOnNlY3JldA==",
        ),
        ("machine wheels.test login reader\n", "Basic cmVhZGVyOg=="),
        (
            "default login wrong password credentials\nmachine wheels.test login reader password secret\n",
            "Basic cmVhZGVyOnNlY3JldA==",
        ),
    ],
)
def test_session_resolves_netrc_machine_fields(
    netrc_path: pathlib.Path, entry: str, expected: str
) -> None:
    """Resolve machine fields without falling back to default credentials."""
    netrc_path.write_text(entry)
    session, _ = create_session()

    request = session.prepare_request(requests.Request("GET", "https://wheels.test/"))

    assert request.headers["Authorization"] == expected


@pytest.mark.parametrize("explicit", [False, True])
def test_session_handles_unsupported_netrc_encoding(
    netrc_path: pathlib.Path, explicit: bool
) -> None:
    """Unsupported Basic credentials do not block explicit authentication."""
    netrc_path.write_text(
        "machine wheels.test login reader password secret雪\n", encoding="utf-8"
    )
    session, _ = create_session()
    headers = {"Authorization": "Bearer explicit"} if explicit else {}

    request = session.prepare_request(
        requests.Request("GET", "https://wheels.test/", headers=headers)
    )

    assert request.headers.get("Authorization") == (
        "Bearer explicit" if explicit else None
    )
