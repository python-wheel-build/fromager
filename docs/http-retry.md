# HTTP Retry and Resilience

Fromager includes enhanced HTTP retry functionality to handle network failures, server timeouts, and rate limiting that can occur when downloading packages and metadata.

## Features

The retry system provides:

- **Exponential backoff with jitter** to avoid thundering herd problems
- **Configurable retry attempts** (default: 8 retries)
- **Smart error handling** for common network issues:
  - HTTP 5xx server errors (500, 502, 503, 504)
  - HTTP 429 rate limiting
  - Connection timeouts and broken connections
  - Incomplete reads during large downloads
  - DNS resolution failures

- **GitHub API rate limit handling** with proper reset time detection
- **GitHub authentication** automatically applied for GitHub API requests via `GITHUB_TOKEN` environment variable
- **Temporary file handling** to prevent partial downloads

## Configuration

You can customize retry behavior using environment variables:

```bash
# Number of retry attempts (default: 8)
export FROMAGER_HTTP_RETRIES=10

# Backoff factor for exponential delay (default: 1.5)
export FROMAGER_HTTP_BACKOFF_FACTOR=2.0

# Request timeout in seconds (default: 120)
export FROMAGER_HTTP_TIMEOUT=180

# Token for GitHub API authentication (prevents rate limiting)
export GITHUB_TOKEN=your_github_token_here
```

## Error Types Handled

The retry mechanism specifically handles these error conditions:

### Server Errors

- `504 Gateway Timeout` - Server overwhelmed or upstream timeout
- `502 Bad Gateway` - Proxy/gateway errors
- `503 Service Unavailable` - Temporary server overload
- `500 Internal Server Error` - General server errors

### Rate Limiting

- `429 Too Many Requests` - General rate limiting
- GitHub API rate limits with proper reset time handling

### Network Errors

- `ConnectionError` - Network connectivity issues
- `ChunkedEncodingError` - Broken connections during transfer
- `IncompleteRead` - Partial data received
- `ProtocolError` - Low-level protocol issues
- `Timeout` - Request timeouts

## Usage

The retry functionality is automatically enabled for all HTTP operations in Fromager. No code changes are required for existing functionality.

### For Plugin Developers

If you're writing plugins that need HTTP functionality, you can use the retry session:

```python
from fromager.http_retry import get_retry_session

# Get a session with retry capabilities
session = get_retry_session()

# Use it like a normal requests session
response = session.get("https://example.com/api/data")
response.raise_for_status()
```

For more advanced retry configuration:

```python
from fromager.http_retry import create_retry_session

# Custom retry configuration
retry_config = {
    "total": 5,
    "backoff_factor": 2.0,
    "status_forcelist": [429, 502, 503, 504],
}

session = create_retry_session(
    retry_config=retry_config,
    timeout=60.0
)
```

### Decorating Functions with Retry Logic

For functions that might fail due to transient errors:

```python
from fromager.http_retry import retry_on_exception, RETRYABLE_EXCEPTIONS

@retry_on_exception(
    exceptions=RETRYABLE_EXCEPTIONS,
    max_attempts=3,
    backoff_factor=1.0,
    max_backoff=30.0,
)
def download_metadata(url):
    # Your download logic here
    pass
```

## Logging

The retry system logs important events:

- **WARNING**: When retries are attempted with backoff times
- **ERROR**: When all retry attempts are exhausted
- **DEBUG**: Detailed retry configuration and GitHub token status

Example log output:

```text
WARNING Request failed for https://api.github.com/repos/owner/repo/tags: 504 Server Error. Retrying in 2.3 seconds (attempt 2/5)
WARNING GitHub API rate limit hit for https://api.github.com/repos/owner/repo/tags. Waiting 1247 seconds until reset.
INFO saved /path/to/package.tar.gz
```

## Performance Considerations

- **Chunk size**: Downloads use 64KB chunks for better error recovery
- **Temporary files**: Partial downloads are written to `.tmp` files first
- **Jitter**: Random delays prevent synchronized retry storms
- **Max backoff**: Delays are capped at 60-120 seconds depending on context

## Troubleshooting

### High Retry Rates

If you're seeing many retries, consider:

- Setting `GITHUB_TOKEN` for GitHub API calls (automatically applied to GitHub requests)
- Increasing timeout values for slow connections
- Checking network connectivity and DNS resolution

### API Rate Limiting

- Use `GITHUB_TOKEN` for GitHub repositories
- Consider using a local package mirror for PyPI
- Monitor API usage if using private registries

### Connection Issues

- Verify firewall and proxy settings
- Check if specific URLs are being blocked
- Consider network-level retry/redundancy
