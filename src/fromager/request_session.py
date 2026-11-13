from __future__ import annotations

import logging
import netrc
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
    callback is invoked and the result is cached. Hosts without a registered
    callback use the optional fallback callback.
    """

    def __init__(self, fallback: _AuthCallback | None = None) -> None:
        self.fallback = fallback
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

        Invokes the registered callback or fallback on first access and caches
        the result. Returns an empty dict when neither applies.
        """
        parsed = urlparse(url)
        key = (parsed.scheme, parsed.hostname or "")
        if key not in self._cache:
            callback = self._callbacks.get(key, self.fallback)
            self._cache[key] = callback(*key) if callback else {}
        return dict(self._cache[key])

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        """Apply resolved headers while preserving headers set by the caller."""
        for name, value in self.get(r.url or "").items():
            r.headers.setdefault(name, value)
        return r


class _AuthenticatedSession(requests.Session):
    """Apply the session's authentication policy to redirected requests."""

    def rebuild_auth(
        self, prepared_request: requests.PreparedRequest, response: requests.Response
    ) -> None:
        """Strip unsafe Authorization headers and resolve destination credentials."""
        if self.should_strip_auth(
            response.request.url or "", prepared_request.url or ""
        ):
            prepared_request.headers.pop("Authorization", None)

        # Requests' implementation performs an unrestricted netrc lookup here.
        if isinstance(self.auth, SessionAuth):
            self.auth(prepared_request)


def _find_netrc() -> str | None:
    """Find netrc using NETRC or the standard home-directory locations."""
    netrc_env = os.environ.get("NETRC")
    candidates = [netrc_env] if netrc_env is not None else ["~/.netrc", "~/_netrc"]
    for candidate in candidates:
        path = os.path.expanduser(candidate)
        if os.path.exists(path):
            return path
    return None


def _resolve_netrc_auth(scheme: str, hostname: str) -> dict[str, str]:
    """Resolve Basic auth from an exact netrc machine entry over HTTPS."""
    if scheme != "https" or not hostname or hostname == "default":
        return {}
    path = _find_netrc()
    if path is None:
        return {}
    try:
        # authenticators() also matches the default entry, which we must ignore.
        entry = netrc.netrc(path).hosts.get(hostname)
    except (netrc.NetrcParseError, OSError, UnicodeError):
        # Parse errors can contain credentials; do not include exception text.
        logger.warning("netrc auth: cannot read credentials from %s", path)
        return {}
    if entry is None or not any(entry):
        return {}
    login, account, password = entry
    request = requests.PreparedRequest()
    request.prepare_headers({})
    try:
        requests.auth.HTTPBasicAuth(login or account or "", password or "")(request)
    except UnicodeEncodeError:
        logger.warning("netrc auth: cannot encode credentials for %s", hostname)
        return {}
    logger.debug("netrc auth: using credentials for %s", hostname)
    return {"Authorization": str(request.headers["Authorization"])}


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
    `SessionAuth` handler keyed by ``(scheme, hostname)``. Other HTTPS hosts
    use exact netrc machine entries as a cached fallback, including on redirects.

    Returns the session and its `SessionAuth` so callers can
    register additional auth callbacks via ``auth.add()``.
    """
    adapter = RetryHTTPAdapter(
        retry_config=FROMAGER_RETRY_CONFIG,
        timeout=float(os.environ.get("FROMAGER_HTTP_TIMEOUT", "120.0")),
    )

    s = _AuthenticatedSession()
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    auth = SessionAuth(fallback=_resolve_netrc_auth)
    auth.add(GITHUB_API_URL, _resolve_github_auth)
    auth.add(GITLAB_CI_SERVER_URL, _resolve_gitlab_auth)
    s.auth = auth

    return s, auth


session, session_auth = create_session()
