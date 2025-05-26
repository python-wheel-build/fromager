import os

from .http_retry import create_retry_session

# Enhanced retry configuration for fromager
FROMAGER_RETRY_CONFIG = {
    "total": int(os.environ.get("FROMAGER_HTTP_RETRIES", "8")),
    "backoff_factor": float(os.environ.get("FROMAGER_HTTP_BACKOFF_FACTOR", "1.5")),
    "status_forcelist": [429, 500, 502, 503, 504],
    "allowed_methods": ["GET", "PUT", "POST", "HEAD", "OPTIONS"],
    "raise_on_status": False,
}

# Create a session with enhanced retry capabilities
session = create_retry_session(
    retry_config=FROMAGER_RETRY_CONFIG,
    timeout=float(os.environ.get("FROMAGER_HTTP_TIMEOUT", "120.0")),
)
