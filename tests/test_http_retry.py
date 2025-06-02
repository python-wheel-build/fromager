import time
from unittest import mock
from unittest.mock import Mock, patch

import pytest
import requests
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,
    ConnectTimeout,
    ReadTimeout,
    RetryError,
    Timeout,
)
from urllib3.exceptions import IncompleteRead, ProtocolError

from fromager import http_retry


class TestRetryHTTPAdapter:
    """Test cases for RetryHTTPAdapter class."""

    def test_init_with_default_config(self):
        """Test adapter initialization with default configuration."""
        adapter = http_retry.RetryHTTPAdapter()
        assert adapter.timeout == 60.0
        assert adapter.backoff_factor == 1.0
        assert adapter.max_backoff == 60.0

    def test_init_with_custom_config(self):
        """Test adapter initialization with custom configuration."""
        custom_config = {
            "total": 3,
            "backoff_factor": 2.0,
            "status_forcelist": [502, 503],
            "allowed_methods": ["GET", "POST"],
            "raise_on_status": True,
        }
        adapter = http_retry.RetryHTTPAdapter(retry_config=custom_config, timeout=30.0)
        assert adapter.timeout == 30.0
        assert adapter.backoff_factor == 2.0

    def test_init_with_invalid_config_types(self):
        """Test adapter handles invalid configuration types gracefully."""
        invalid_config = {
            "total": "invalid",
            "backoff_factor": "invalid",
            "status_forcelist": "invalid",
            "allowed_methods": "invalid",
            "raise_on_status": "invalid",
        }
        adapter = http_retry.RetryHTTPAdapter(retry_config=invalid_config)
        # Should use defaults when invalid types are provided
        assert adapter.backoff_factor == 1.0

    @patch("fromager.http_retry.RetryHTTPAdapter._handle_github_rate_limit")
    @patch("requests.adapters.HTTPAdapter.send")
    def test_send_successful_response(self, mock_super_send, mock_github_handler):
        """Test successful HTTP request without retries."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"

        response = Mock(spec=requests.Response)
        response.status_code = 200
        mock_super_send.return_value = response

        result = adapter.send(request)

        assert result == response
        mock_super_send.assert_called_once()
        mock_github_handler.assert_not_called()

    @patch("time.sleep")
    @patch("requests.adapters.HTTPAdapter.send")
    def test_send_retries_on_server_errors(self, mock_super_send, mock_sleep):
        """Test retry behavior on server error status codes."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"

        error_response = Mock(spec=requests.Response)
        error_response.status_code = 502
        success_response = Mock(spec=requests.Response)
        success_response.status_code = 200

        mock_super_send.side_effect = [error_response, success_response]

        result = adapter.send(request)

        assert result == success_response
        assert mock_super_send.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("requests.adapters.HTTPAdapter.send")
    def test_send_github_rate_limit_handling(self, mock_super_send, mock_sleep):
        """Test GitHub API rate limit handling."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://api.github.com/repos/test"

        rate_limit_response = Mock(spec=requests.Response)
        rate_limit_response.status_code = 403
        rate_limit_response.text = "API rate limit exceeded"
        rate_limit_response.headers = {"X-RateLimit-Reset": str(int(time.time()) + 60)}
        rate_limit_response.request = request

        success_response = Mock(spec=requests.Response)
        success_response.status_code = 200

        mock_super_send.side_effect = [rate_limit_response, success_response]

        result = adapter.send(request)

        assert result == success_response
        assert mock_super_send.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    @patch("requests.adapters.HTTPAdapter.send")
    def test_send_retries_on_connection_error(self, mock_super_send, mock_sleep):
        """Test retry behavior on connection errors."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"

        success_response = Mock(spec=requests.Response)
        success_response.status_code = 200

        # First call raises ConnectionError, second succeeds
        mock_super_send.side_effect = [
            ConnectionError("Connection failed"),
            success_response,
        ]

        result = adapter.send(request)

        assert result == success_response
        assert mock_super_send.call_count == 2
        mock_sleep.assert_called_once()

    @patch("requests.adapters.HTTPAdapter.send")
    def test_send_exhausts_retries_and_raises(self, mock_super_send):
        """Test that retries are exhausted and exception is raised."""
        adapter = http_retry.RetryHTTPAdapter(retry_config={"total": 1})
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"

        mock_super_send.side_effect = ConnectionError("Persistent connection error")

        with pytest.raises(ConnectionError):
            adapter.send(request)

    def test_handle_github_rate_limit_with_reset_header(self):
        """Test GitHub rate limit handling with reset header."""
        adapter = http_retry.RetryHTTPAdapter()
        response = Mock(spec=requests.Response)
        response.headers = {"X-RateLimit-Reset": str(int(time.time()) + 1)}
        response.request = Mock()
        response.request.url = "https://api.github.com"

        with patch("time.sleep") as mock_sleep:
            adapter._handle_github_rate_limit(response, 0, 3)
            mock_sleep.assert_called_once()

    def test_handle_github_rate_limit_without_reset_header(self):
        """Test GitHub rate limit handling without reset header."""
        adapter = http_retry.RetryHTTPAdapter()
        response = Mock(spec=requests.Response)
        response.headers = {}
        response.request = Mock()
        response.request.url = "https://api.github.com"

        with patch("time.sleep") as mock_sleep:
            adapter._handle_github_rate_limit(response, 0, 3)
            mock_sleep.assert_called_once()

    def test_handle_retryable_exception(self):
        """Test handling of retryable exceptions."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"
        exception = ConnectionError("Test error")

        with patch("time.sleep") as mock_sleep:
            adapter._handle_retryable_exception(exception, request, 0, 3)
            mock_sleep.assert_called_once()

    def test_handle_retryable_exception_max_attempts(self):
        """Test handling retryable exception at max attempts."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"
        exception = ConnectionError("Test error")

        with patch("time.sleep") as mock_sleep:
            adapter._handle_retryable_exception(exception, request, 2, 3)
            mock_sleep.assert_not_called()


class TestCreateRetrySession:
    """Test cases for create_retry_session function."""

    def test_create_retry_session_default(self):
        """Test creating a retry session with default configuration."""
        session = http_retry.create_retry_session()
        assert isinstance(session, requests.Session)
        assert "http://" in session.adapters
        assert "https://" in session.adapters

    def test_create_retry_session_custom_config(self):
        """Test creating a retry session with custom configuration."""
        custom_config = {"total": 3, "backoff_factor": 2.0}
        session = http_retry.create_retry_session(
            retry_config=custom_config, timeout=30.0
        )
        assert isinstance(session, requests.Session)

    def test_create_retry_session_basic(self):
        """Test basic session creation."""
        session = http_retry.create_retry_session()
        assert isinstance(session.get_adapter("http://"), http_retry.RetryHTTPAdapter)
        assert isinstance(session.get_adapter("https://"), http_retry.RetryHTTPAdapter)
        assert "Authorization" not in session.headers


class TestRetryOnExceptionDecorator:
    """Test cases for retry_on_exception decorator."""

    def test_retry_decorator_success_on_first_attempt(self):
        """Test decorator when function succeeds on first attempt."""

        @http_retry.retry_on_exception(max_attempts=3)
        def successful_function():
            return "success"

        result = successful_function()
        assert result == "success"

    def test_retry_decorator_success_after_retries(self):
        """Test decorator when function succeeds after retries."""
        call_count = 0

        @http_retry.retry_on_exception(max_attempts=3, backoff_factor=0.01)
        def failing_then_succeeding_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        with patch("time.sleep"):
            result = failing_then_succeeding_function()
            assert result == "success"
            assert call_count == 3

    def test_retry_decorator_exhausts_attempts(self):
        """Test decorator when all retry attempts are exhausted."""

        @http_retry.retry_on_exception(max_attempts=2, backoff_factor=0.01)
        def always_failing_function():
            raise ConnectionError("Persistent failure")

        with patch("time.sleep"):
            with pytest.raises(ConnectionError):
                always_failing_function()

    def test_retry_decorator_non_retryable_exception(self):
        """Test decorator with non-retryable exception."""

        @http_retry.retry_on_exception(exceptions=(ConnectionError,), max_attempts=3)
        def function_with_non_retryable_exception():
            raise ValueError("Non-retryable error")

        with pytest.raises(ValueError):
            function_with_non_retryable_exception()

    def test_retry_decorator_custom_exceptions(self):
        """Test decorator with custom exception types."""

        @http_retry.retry_on_exception(
            exceptions=(ValueError, TypeError), max_attempts=2, backoff_factor=0.01
        )
        def function_with_custom_exceptions():
            raise ValueError("Custom retryable error")

        with patch("time.sleep"):
            with pytest.raises(ValueError):
                function_with_custom_exceptions()

    def test_retry_decorator_with_function_arguments(self):
        """Test decorator preserves function arguments."""

        @http_retry.retry_on_exception(max_attempts=2)
        def function_with_args(arg1, arg2, kwarg1=None):
            return f"{arg1}-{arg2}-{kwarg1}"

        result = function_with_args("a", "b", kwarg1="c")
        assert result == "a-b-c"


class TestGetRetrySession:
    """Test cases for get_retry_session function."""

    def test_get_retry_session(self):
        """Test getting a pre-configured retry session."""
        session = http_retry.get_retry_session()
        assert isinstance(session, requests.Session)
        assert "http://" in session.adapters
        assert "https://" in session.adapters


class TestDefaultRetryConfig:
    """Test cases for default retry configuration."""

    def test_default_retry_config_values(self):
        """Test that default retry configuration has expected values."""
        config = http_retry.DEFAULT_RETRY_CONFIG
        assert config["total"] == 5
        assert config["backoff_factor"] == 1.0
        assert 429 in config["status_forcelist"]
        assert 502 in config["status_forcelist"]
        assert "GET" in config["allowed_methods"]
        assert config["raise_on_status"] is False


class TestRetryableExceptions:
    """Test cases for retryable exceptions tuple."""

    def test_retryable_exceptions_contains_expected_types(self):
        """Test that RETRYABLE_EXCEPTIONS contains expected exception types."""
        exceptions = http_retry.RETRYABLE_EXCEPTIONS
        assert ConnectionError in exceptions
        assert Timeout in exceptions
        assert ChunkedEncodingError in exceptions
        assert IncompleteRead in exceptions
        assert ProtocolError in exceptions
        assert RetryError in exceptions
        assert ConnectTimeout in exceptions
        assert ReadTimeout in exceptions


class TestIntegration:
    """Integration test cases."""

    def test_end_to_end_retry_session(self):
        """Test end-to-end usage of retry session."""
        # Test that we can create a session and access its adapters
        session = http_retry.create_retry_session()

        # Verify session has retry adapters mounted
        assert isinstance(session.adapters["http://"], http_retry.RetryHTTPAdapter)
        assert isinstance(session.adapters["https://"], http_retry.RetryHTTPAdapter)

        # Verify session has proper timeout configuration
        http_adapter = session.adapters["https://"]
        assert http_adapter.timeout == 60.0

    def test_adapter_with_various_retryable_exceptions(self):
        """Test adapter handles various retryable exceptions."""
        adapter = http_retry.RetryHTTPAdapter(retry_config={"total": 1})
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"

        # Test each retryable exception type
        retryable_exceptions = [
            ConnectionError("Connection failed"),
            Timeout("Request timed out"),
            ChunkedEncodingError("Chunked encoding error"),
            IncompleteRead(partial=10, expected=20),
            ProtocolError("Protocol error"),
        ]

        for exception in retryable_exceptions:
            with patch("requests.adapters.HTTPAdapter.send") as mock_send:
                mock_send.side_effect = exception
                with patch("time.sleep"):
                    with pytest.raises(type(exception)):
                        adapter.send(request)

    @patch("time.sleep")
    @patch("random.uniform", return_value=0.5)
    def test_backoff_calculation(self, mock_random, mock_sleep):
        """Test backoff time calculation with jitter."""
        adapter = http_retry.RetryHTTPAdapter()
        request = Mock(spec=requests.PreparedRequest)
        request.url = "https://example.com"
        exception = ConnectionError("Test error")

        adapter._handle_retryable_exception(exception, request, 1, 5)

        # Expected: min(2^1 + 0.5, 60) = min(2.5, 60) = 2.5
        mock_sleep.assert_called_once_with(2.5)


# Test standalone functions
def test_default_retry_config_structure():
    """Test that DEFAULT_RETRY_CONFIG has the correct structure."""
    config = http_retry.DEFAULT_RETRY_CONFIG
    expected_keys = {
        "total",
        "backoff_factor",
        "status_forcelist",
        "allowed_methods",
        "raise_on_status",
    }
    assert set(config.keys()) == expected_keys


def test_retryable_exceptions_tuple_is_not_empty():
    """Test that RETRYABLE_EXCEPTIONS is not empty."""
    assert len(http_retry.RETRYABLE_EXCEPTIONS) > 0


@patch("time.sleep")
@patch("random.uniform", return_value=0.1)
def test_retry_decorator_backoff_timing(mock_random, mock_sleep):
    """Test retry decorator backoff timing calculation."""
    call_count = 0

    @http_retry.retry_on_exception(max_attempts=3, backoff_factor=2.0, max_backoff=10.0)
    def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Temporary failure")
        return "success"

    result = failing_function()

    assert result == "success"
    assert call_count == 3
    # Check that sleep was called with expected backoff times
    expected_calls = [
        mock.call(2.1),  # 2.0 * (2^0) + 0.1 = 2.1
        mock.call(4.1),  # 2.0 * (2^1) + 0.1 = 4.1
    ]
    mock_sleep.assert_has_calls(expected_calls)


@patch("fromager.http_retry.logger")
def test_adapter_logging_on_retry(mock_logger):
    """Test that appropriate logging occurs during retries."""
    adapter = http_retry.RetryHTTPAdapter()
    request = Mock(spec=requests.PreparedRequest)
    request.url = "https://example.com"
    exception = ConnectionError("Test error")

    with patch("time.sleep"):
        adapter._handle_retryable_exception(exception, request, 0, 3)

    mock_logger.warning.assert_called_once()
    call_args = mock_logger.warning.call_args
    assert len(call_args[0]) > 1
    assert "Request failed for %s" in call_args[0][0]
    assert "https://example.com" in call_args[0]


@patch("fromager.http_retry.logger")
def test_adapter_logging_on_github_rate_limit(mock_logger):
    """Test logging during GitHub rate limit handling."""
    adapter = http_retry.RetryHTTPAdapter()
    response = Mock(spec=requests.Response)
    response.headers = {}
    response.request = Mock()
    response.request.url = "https://api.github.com"

    with patch("time.sleep"):
        adapter._handle_github_rate_limit(response, 0, 3)

    mock_logger.warning.assert_called_once()
    args = mock_logger.warning.call_args[0]
    assert "GitHub API rate limit hit" in args[0]
