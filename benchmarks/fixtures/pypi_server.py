"""
Local PyPI server fixture for network-isolated benchmarks.
Uses Python's built-in http.server to implement a PEP 503 Simple Repository API.
"""

from __future__ import annotations

import functools
import http.server
import pathlib
import shutil
import socketserver
import threading
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Generator


class LocalPyPI:
    """A minimal PEP 503 Simple Repository server for testing.

    Attributes:
        root_dir: The root directory containing the /simple/ structure
        port: The port the server is listening on (0 = auto-assigned)
        url: The base URL for the simple API
        packages_dir: The directory where package files are stored
    """

    def __init__(self, root_dir: pathlib.Path) -> None:
        self.root_dir = root_dir
        self.port = 0
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

        # Create the /simple/ directory structure
        self.packages_dir = self.root_dir / "simple"
        self.packages_dir.mkdir(parents=True, exist_ok=True)

        # Create root index
        self._update_root_index()

    @property
    def url(self) -> str:
        """The --index-url to pass to pip/uv."""
        return f"http://localhost:{self.port}/simple/"

    def add_package(self, name: str, wheel_path: pathlib.Path) -> None:
        """Add a wheel to the repository and regenerate the index.

        Args:
            name: Normalized package name (e.g., 'my-package')
            wheel_path: Path to the .whl or .tar.gz file to serve
        """
        # Create PEP 503 structure: /simple/<project>/
        pkg_dir = self.packages_dir / name.lower().replace("_", "-")
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Copy the distribution file
        dest = pkg_dir / wheel_path.name
        shutil.copy(wheel_path, dest)

        # Generate PEP 503 index.html for this package
        self._update_package_index(pkg_dir)

        # Update root index
        self._update_root_index()

    def _update_package_index(self, pkg_dir: pathlib.Path) -> None:
        """Generate the index.html for a single package directory."""
        links = []
        for f in pkg_dir.iterdir():
            if f.suffix in (".whl", ".gz"):
                links.append(f'<a href="{f.name}">{f.name}</a><br>')

        index_content = f"""<!DOCTYPE html>
<html>
<head><title>Links for {pkg_dir.name}</title></head>
<body>
<h1>Links for {pkg_dir.name}</h1>
{''.join(links)}
</body>
</html>"""
        (pkg_dir / "index.html").write_text(index_content)

    def _update_root_index(self) -> None:
        """Generate the root /simple/ index.html listing all packages."""
        links = []
        for pkg_dir in sorted(self.packages_dir.iterdir()):
            if pkg_dir.is_dir():
                links.append(f'<a href="{pkg_dir.name}/">{pkg_dir.name}</a><br>')

        index_content = f"""<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
{''.join(links)}
</body>
</html>"""
        (self.packages_dir / "index.html").write_text(index_content)

    def start(self) -> None:
        """Start the HTTP server in a background thread."""

        # Create a handler that serves from our root directory
        handler = functools.partial(
            _SilentHTTPRequestHandler, directory=str(self.root_dir)
        )

        # Use port 0 to let the OS assign a free port
        self._httpd = socketserver.TCPServer(("localhost", 0), handler)
        self.port = self._httpd.server_address[1]

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


class _SilentHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that suppresses access logs."""

    def log_message(self, format: str, *args: object) -> None:
        """Silence all log messages."""
        pass


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Poll server until ready or timeout."""
    import urllib.error
    import urllib.request

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1.0)
            return True
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.1)
    return False


@pytest.fixture(scope="session")
def local_pypi(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[LocalPyPI, None, None]:
    """Start a local PyPI server for benchmarks.

    Uses Python's built-in http.server to serve packages from a temporary
    directory. The server runs on a dynamically assigned port for the
    duration of the test session.

    Example:
        def test_install(local_pypi):
            local_pypi.add_package("mypkg", path_to_wheel)
            # Use local_pypi.url as --index-url
    """
    root_dir = tmp_path_factory.mktemp("pypi_root")

    server = LocalPyPI(root_dir)
    server.start()

    # Wait for server to be ready
    if not _wait_for_server(server.url):
        server.stop()
        raise RuntimeError(
            f"Local PyPI server failed to start on port {server.port}"
        )

    yield server

    server.stop()
