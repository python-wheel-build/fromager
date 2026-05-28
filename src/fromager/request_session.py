from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests.auth
from requests.utils import get_netrc_auth

from .http_retry import RetryHTTPAdapter

logger = logging.getLogger(__name__)

# Enhanced retry configuration for fromager
FROMAGER_RETRY_CONFIG = {
    "total": int(os.environ.get("FROMAGER_HTTP_RETRIES", "8")),
    "backoff_factor": float(os.environ.get("FROMAGER_HTTP_BACKOFF_FACTOR", "1.5")),
    "status_forcelist": [408, 429, 500, 502, 503, 504],
    "allowed_methods": ["GET", "PUT", "POST", "HEAD", "OPTIONS"],
    "raise_on_status": False,
}

GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com")

GITLAB_CI_SERVER_URL = os.environ.get("CI_SERVER_URL", "https://gitlab.com")
GITLAB_JOB_TOKEN_NAME = "gitlab-ci-token"


if TYPE_CHECKING:
    from collections.abc import Callable

    _AuthCallback = Callable[[str, str], dict[str, str]]


class SessionAuth(requests.auth.AuthBase):
    """Authentication handler that dispatches by ``(scheme, hostname)``.

    The requests library only supports a single ``session.auth`` handler
    and does not provide per-host authentication on mounted adapters.
    This class fills that gap by mapping ``(scheme, hostname)`` keys to
    auth resolver callbacks. On the first request to a given host the
    callback is invoked and the result is cached.
    """

    def __init__(self) -> None:
        self._callbacks: dict[tuple[str, str], _AuthCallback] = {}
        self._cache: dict[tuple[str, str], dict[str, str]] = {}

    def add(self, url: str, callback: _AuthCallback) -> None:
        """Register a resolver *callback* for the scheme and hostname of *url*."""
        parsed = urlparse(url)
        scheme = parsed.scheme
        hostname = parsed.hostname or ""
        if scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported scheme {scheme!r} in URL {url!r}")
        if not hostname:
            raise ValueError(f"Missing hostname in URL {url!r}")
        key = (scheme, hostname)
        self._cache.pop(key, None)
        self._callbacks[key] = callback

    def get(self, url: str) -> dict[str, str]:
        """Resolve and return the auth headers for *url*.

        Invokes the registered callback on first access and caches the
        result.  Returns an empty dict when no callback is registered.
        """
        parsed = urlparse(url)
        key = (parsed.scheme, parsed.hostname or "")
        if key not in self._cache:
            callback = self._callbacks.get(key)
            self._cache[key] = callback(*key) if callback else {}
        return dict(self._cache[key])

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        auth_header = self.get(r.url or "")
        if auth_header:
            r.headers.update(auth_header)
        return r


def _resolve_github_auth(scheme: str, hostname: str) -> dict[str, str]:
    """Resolve GitHub auth header from netrc or environment."""
    url = f"{scheme}://{hostname}"
    netrc_auth = get_netrc_auth(url)
    if netrc_auth is not None:
        _login, password = netrc_auth
        logger.debug("GitHub auth: using netrc credentials for %s", url)
        return {"Authorization": f"token {password}"}

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        logger.debug("GitHub auth: using GITHUB_TOKEN environment variable")
        return {"Authorization": f"token {token}"}
    return {}


def _resolve_gitlab_auth(scheme: str, hostname: str) -> dict[str, str]:
    """Resolve GitLab auth header from netrc or environment."""
    url = f"{scheme}://{hostname}"
    netrc_auth = get_netrc_auth(url)
    if netrc_auth is not None:
        login, password = netrc_auth
        header = "JOB-TOKEN" if login == GITLAB_JOB_TOKEN_NAME else "PRIVATE-TOKEN"
        logger.debug("GitLab auth: using netrc credentials for %s (%s)", url, header)
        return {header: password}

    token = os.environ.get("CI_JOB_TOKEN")
    if token:
        logger.debug("GitLab auth: using CI_JOB_TOKEN environment variable")
        return {"JOB-TOKEN": token}

    token = os.environ.get("GITLAB_PRIVATE_TOKEN")
    if token:
        logger.debug("GitLab auth: using GITLAB_PRIVATE_TOKEN environment variable")
        return {"PRIVATE-TOKEN": token}
    return {}


def create_session() -> tuple[requests.Session, SessionAuth]:
    """Create a requests session with retry and authentication.

    Mounts a `RetryHTTPAdapter` on ``http://`` and ``https://``.
    Registers lazy auth callbacks for GitHub and GitLab on a
    `SessionAuth` handler keyed by ``(scheme, hostname)``.

    Returns the session and its `SessionAuth` so callers can
    register additional auth callbacks via ``auth.add()``.
    """
    adapter = RetryHTTPAdapter(
        retry_config=FROMAGER_RETRY_CONFIG,
        timeout=float(os.environ.get("FROMAGER_HTTP_TIMEOUT", "120.0")),
    )

    s = requests.Session()
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    auth = SessionAuth()
    auth.add(GITHUB_API_URL, _resolve_github_auth)
    auth.add(GITLAB_CI_SERVER_URL, _resolve_gitlab_auth)
    s.auth = auth

    return s, auth


session, session_auth = create_session()
