"""Minimal mock GitHub API server for e2e tests.

Serves static tag JSON for the stevedore-test-repo at the expected
GitHub API path.
"""

from __future__ import annotations

import pathlib
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

TAGS_PATH = "/repos/python-wheel-build/stevedore-test-repo/tags"
TAGS_JSON = (pathlib.Path(__file__).parent / "tags.json").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == TAGS_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(TAGS_JSON)
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9998
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Mock GitHub API listening on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
