"""HTTP retry utilities for resilient network operations.

This module provides a robust retry mechanism for HTTP requests with exponential
backoff, jitter, and specific handling for common network failures including:
- Server timeouts (502, 503, 504)
- Rate limiting (429, GitHub API rate limits)
- Connection errors and incomplete reads
- DNS resolution failures

The retry session can be used as a drop-in replacement for the standard
requests session in most cases.
"""

from __future__ import annotations

import logging
import random
import time
import typing

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,
    RequestException,
    Timeout,
)
from urllib3.exceptions import IncompleteRead, ProtocolError
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_RETRY_CONFIG = {
    "total": 5,
    "backoff_factor": 1.0,
    "status_forcelist": [429, 500, 502, 503, 504],
    "allowed_methods": ["GET", "PUT", "POST", "HEAD", "OPTIONS"],
    "raise_on_status": False,
}

# Exceptions that should trigger a retry
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    Timeout,
    ChunkedEncodingError,
    IncompleteRead,
    ProtocolError,
    # Add more urllib3 exceptions that are often transient
    requests.exceptions.RetryError,
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout,
)


class RetryHTTPAdapter(HTTPAdapter):
    """HTTP adapter with enhanced retry logic and backoff."""

    def __init__(
        self,
        retry_config: dict[str, typing.Any] | None = None,
        timeout: float = 60.0,
        **kwargs: typing.Any,
    ):
        """Initialize the retry adapter.

        Args:
            retry_config: Configuration for urllib3 Retry. If None, uses DEFAULT_RETRY_CONFIG.
            timeout: Default timeout for requests in seconds.
            **kwargs: Additional arguments passed to HTTPAdapter.
        """
        self.timeout = timeout
        config = retry_config or DEFAULT_RETRY_CONFIG.copy()

        # Store configuration for use in send method with proper type handling
        backoff_factor_val = config.get("backoff_factor", 1.0)
        self.backoff_factor: float = (
            1.0
            if not isinstance(backoff_factor_val, int | float)
            else float(backoff_factor_val)
        )
        self.max_backoff: float = 60.0  # Maximum backoff time in seconds

        # Create the retry strategy with proper type handling
        total_val = config.get("total", 5)
        total = 5 if not isinstance(total_val, int | float) else int(total_val)

        backoff_val = config.get("backoff_factor", 1.0)
        backoff = (
            1.0 if not isinstance(backoff_val, int | float) else float(backoff_val)
        )

        status_list_val = config.get("status_forcelist", [429, 500, 502, 503, 504])
        status_list = (
            [429, 500, 502, 503, 504]
            if not isinstance(status_list_val, list)
            else status_list_val
        )

        methods_val = config.get(
            "allowed_methods", ["GET", "PUT", "POST", "HEAD", "OPTIONS"]
        )
        methods = (
            ["GET", "PUT", "POST", "HEAD", "OPTIONS"]
            if not isinstance(methods_val, list)
            else methods_val
        )

        raise_on_status_val = config.get("raise_on_status", False)
        raise_on_status = (
            False if not isinstance(raise_on_status_val, bool) else raise_on_status_val
        )

        retry_strategy = Retry(
            total=total,
            backoff_factor=backoff,
            status_forcelist=status_list,
            allowed_methods=methods,
            raise_on_status=raise_on_status,
        )

        super().__init__(max_retries=retry_strategy, **kwargs)

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: typing.Mapping[str, str] | None = None,
        **kwargs: typing.Any,
    ) -> requests.Response:
        """Send request with enhanced error handling and retry logic."""
        if timeout is None:
            timeout = self.timeout

        send_kwargs = {
            "stream": stream,
            "timeout": timeout,
            "verify": verify,
            "cert": cert,
            "proxies": proxies,
            **kwargs,
        }

        max_attempts = getattr(self.max_retries, "total", 5) + 1

        for attempt in range(max_attempts):
            try:
                response = super().send(request, **send_kwargs)

                # Handle GitHub API rate limiting specifically
                if (
                    response.status_code == 403
                    and request.url is not None
                    and "api.github.com" in request.url
                    and "rate limit" in response.text.lower()
                ):
                    self._handle_github_rate_limit(response, attempt, max_attempts)
                    continue

                # Check for retryable HTTP status codes
                if response.status_code in {500, 502, 503, 504}:
                    if attempt >= max_attempts - 1:
                        logger.error(
                            "Request failed with status %d after %d attempts for %s",
                            response.status_code,
                            max_attempts,
                            request.url or "<unknown>",
                        )
                        return response

                    wait_time = min(
                        self.backoff_factor * (2**attempt) + random.uniform(0, 1),
                        self.max_backoff,
                    )

                    logger.warning(
                        "Request failed with status %d for %s. Retrying in %.1f seconds (attempt %d/%d)",
                        response.status_code,
                        request.url or "<unknown>",
                        wait_time,
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(wait_time)
                    continue

                return response

            except RETRYABLE_EXCEPTIONS as e:
                self._handle_retryable_exception(e, request, attempt, max_attempts)
                if attempt == max_attempts - 1:
                    raise
                continue

        # This should not be reached, but just in case
        raise RequestException(
            f"Failed to complete request after {max_attempts} attempts"
        )

    def _handle_github_rate_limit(
        self, response: requests.Response, attempt: int, max_attempts: int
    ) -> None:
        """Handle GitHub API rate limiting with appropriate backoff."""
        if attempt >= max_attempts - 1:
            logger.error(
                "GitHub API rate limit exceeded after %d attempts for %s",
                max_attempts,
                response.request.url or "<unknown>",
            )
            return

        # Check for reset time in headers
        reset_time = response.headers.get("X-RateLimit-Reset")
        if reset_time:
            try:
                reset_timestamp = int(reset_time)
                current_time = int(time.time())
                wait_time = min(
                    reset_timestamp - current_time + 5, 300
                )  # Max 5 minutes
                if wait_time > 0:
                    logger.warning(
                        "GitHub API rate limit hit for %s. Waiting %d seconds until reset.",
                        response.request.url or "<unknown>",
                        wait_time,
                    )
                    time.sleep(wait_time)
                    return
            except (ValueError, TypeError):
                logger.debug("Could not parse GitHub rate limit reset time")

        # Fallback to exponential backoff
        wait_time = min(2**attempt + random.uniform(0, 1), 60)
        logger.warning(
            "GitHub API rate limit hit for %s. Retrying in %.1f seconds (attempt %d/%d)",
            response.request.url or "<unknown>",
            wait_time,
            attempt + 1,
            max_attempts,
        )
        time.sleep(wait_time)

    def _handle_retryable_exception(
        self,
        exception: Exception,
        request: requests.PreparedRequest,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Handle retryable exceptions with exponential backoff."""
        if attempt >= max_attempts - 1:
            logger.error(
                "Request failed after %d attempts for %s: %s",
                max_attempts,
                request.url or "<unknown>",
                exception,
            )
            return

        # Calculate backoff time with jitter
        wait_time = min(2**attempt + random.uniform(0, 1), 60)

        logger.warning(
            "Request failed for %s: %s. Retrying in %.1f seconds (attempt %d/%d)",
            request.url or "<unknown>",
            exception,
            wait_time,
            attempt + 1,
            max_attempts,
        )
        time.sleep(wait_time)


def create_retry_session(
    retry_config: dict[str, typing.Any] | None = None,
    timeout: float = 60.0,
) -> requests.Session:
    """Create a requests Session with retry capabilities.

    Args:
        retry_config: Configuration for retry behavior. If None, uses DEFAULT_RETRY_CONFIG.
        timeout: Default timeout for requests in seconds.

    Returns:
        A configured requests.Session with retry capabilities.
    """
    session = requests.Session()
    adapter = RetryHTTPAdapter(retry_config=retry_config, timeout=timeout)

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def retry_on_exception(
    exceptions: tuple[type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    max_attempts: int = 5,
    backoff_factor: float = 1.0,
    max_backoff: float = 60.0,
) -> typing.Callable[
    [typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]
]:
    """Decorator to retry a function on specific exceptions.

    Args:
        exceptions: Tuple of exception types that should trigger a retry.
        max_attempts: Maximum number of attempts.
        backoff_factor: Factor for exponential backoff.
        max_backoff: Maximum backoff time in seconds.

    Returns:
        Decorator function.
    """

    def decorator(
        func: typing.Callable[..., typing.Any],
    ) -> typing.Callable[..., typing.Any]:
        def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt >= max_attempts - 1:
                        logger.error(
                            "Function %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            e,
                        )
                        raise

                    wait_time = min(
                        backoff_factor * (2**attempt) + random.uniform(0, 1),
                        max_backoff,
                    )

                    logger.warning(
                        "Function %s failed: %s. Retrying in %.1f seconds (attempt %d/%d)",
                        func.__name__,
                        e,
                        wait_time,
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(wait_time)

            # This should not be reached due to the raise in the exception handler
            raise RuntimeError(f"Retry logic failed for {func.__name__}")

        return wrapper

    return decorator


# For backward compatibility and ease of use
def get_retry_session() -> requests.Session:
    """Get a pre-configured retry session with sensible defaults.

    This is the recommended way to get a session for general use.
    """
    return create_retry_session()
