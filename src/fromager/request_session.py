from __future__ import annotations

import base64
import logging
import os
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

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
    callback is invoked and the result is cached. Hosts without a
    registered callback use the optional default callback instead.
    """

    def __init__(self) -> None:
        self._default: _AuthCallback | None = None
        self._callbacks: dict[tuple[str, str], _AuthCallback] = {}
        self._cache: dict[tuple[str, str], dict[str, str]] = {}

    def set_default(self, callback: _AuthCallback) -> None:
        """Set the fallback *callback* used for unregistered hosts.

        Clears the cache so entries are refreshed.

        .. versionadded:: 0.105.0
        """
        self._default = callback
        self._cache.clear()

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

        Invokes the registered callback or the default callback on first
        access and caches the result. Returns an empty dict when neither
        applies.
        """
        parsed = urlparse(url)
        key = (parsed.scheme, parsed.hostname or "")
        if key not in self._cache:
            callback = self._callbacks.get(key, self._default)
            self._cache[key] = callback(*key) if callback else {}
        return dict(self._cache[key])

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        auth_header = self.get(r.url or "")
        if auth_header:
            r.headers.update(auth_header)
        return r


def _build_url(scheme: str, hostname: str) -> str:
    """Build a URL from *scheme* and *hostname*.

    IPv6 literals are bracketed, because `urlparse()` strips the brackets
    from ``hostname``.
    """
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    return urlunparse((scheme, netloc, "", "", "", ""))


def resolve_netrc_basic_auth(scheme: str, hostname: str) -> dict[str, str]:
    """Resolve HTTP Basic auth from netrc for *hostname*.

    Uses `get_netrc_auth()` to look up credentials. It searches the file
    named by the ``NETRC`` environment variable, then ``~/.netrc`` and
    ``~/_netrc``, and falls back to the ``default`` entry when no
    ``machine`` entry matches the host. Returns an empty dict when no
    credentials are found.

    .. versionadded:: 0.105.0
    """
    netrc_auth = get_netrc_auth(_build_url(scheme, hostname))
    if netrc_auth is None:
        return {}
    login, password = netrc_auth
    credentials = f"{login}:{password}".encode("latin-1")
    token = base64.b64encode(credentials).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _resolve_github_auth(scheme: str, hostname: str) -> dict[str, str]:
    """Resolve GitHub auth header from netrc or environment."""
    url = _build_url(scheme, hostname)
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
    url = _build_url(scheme, hostname)
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
    `SessionAuth` handler keyed by ``(scheme, hostname)``. Other hosts
    fall back to netrc Basic authentication.

    Returns the session and its `SessionAuth` so callers can
    register additional auth callbacks via ``auth.add()``.

    .. versionchanged:: 0.105.0
       Fall back to netrc Basic authentication for hosts without a
       registered callback.
    """
    adapter = RetryHTTPAdapter(
        retry_config=FROMAGER_RETRY_CONFIG,
        timeout=float(os.environ.get("FROMAGER_HTTP_TIMEOUT", "120.0")),
    )

    s = requests.Session()
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    auth = SessionAuth()
    auth.set_default(resolve_netrc_basic_auth)
    auth.add(GITHUB_API_URL, _resolve_github_auth)
    auth.add(GITLAB_CI_SERVER_URL, _resolve_gitlab_auth)
    s.auth = auth

    return s, auth


session, session_auth = create_session()
