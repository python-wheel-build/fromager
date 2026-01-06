"""uv shim fixture for subprocess isolation."""

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytest import TempPathFactory

UV_SHIM_SCRIPT = '''#!/usr/bin/env python3
"""Fixed-cost uv shim for benchmark isolation.

This shim replaces the real uv binary during benchmarks to provide
deterministic timing and isolate the code under test from subprocess
execution variance.
"""
import sys
import time

time.sleep(0.01)  # Fixed minimal delay
sys.exit(0)
'''


@pytest.fixture(scope="session")
def uv_shim(tmp_path_factory: "TempPathFactory") -> Path:
    """Create a uv shim for subprocess isolation.

    This fixture creates a fake uv binary that returns immediately,
    allowing benchmarks to measure only the code under test without
    subprocess execution overhead.

    The shim is created once per session and reused across all tests.
    """
    shim_dir = tmp_path_factory.mktemp("uv_shim")
    shim_path = shim_dir / "uv"

    shim_path.write_text(UV_SHIM_SCRIPT)
    shim_path.chmod(shim_path.stat().st_mode | stat.S_IEXEC)

    return shim_path


@pytest.fixture
def with_uv_shim(uv_shim: Path, monkeypatch: "MonkeyPatch") -> Generator[Path, None, None]:
    """Prepend uv shim directory to PATH.

    This fixture modifies the PATH environment variable so that the
    shim uv binary is found before the real one.
    """
    shim_dir = str(uv_shim.parent)
    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{shim_dir}:{current_path}")
    yield uv_shim
