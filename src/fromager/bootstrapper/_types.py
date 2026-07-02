from __future__ import annotations

import dataclasses
import logging
import pathlib
import typing
from enum import StrEnum

from packaging.utils import NormalizedName

from .. import build_environment, threading_utils
from ..requirements_file import SourceType

logger = logging.getLogger(__name__)

# package name, extras, version, sdist/wheel
SeenKey = tuple[NormalizedName, tuple[str, ...], str, typing.Literal["sdist", "wheel"]]

_DEFAULT_BG_THREADS: int = max(1, threading_utils.get_cpu_count() // 2)


@dataclasses.dataclass
class SourceBuildResult:
    """Result of building or downloading a package.

    Captures the output artifacts from either a source build or
    prebuilt wheel download, used across bootstrap phases.
    """

    wheel_filename: pathlib.Path | None
    sdist_filename: pathlib.Path | None
    unpack_dir: pathlib.Path
    sdist_root_dir: pathlib.Path | None
    build_env: build_environment.BuildEnvironment | None
    source_type: SourceType


@dataclasses.dataclass
class PreparedSourceData:
    """Result of background I/O pre-fetching returned to the main thread.

    Fields are set in one of three combinations depending on the result type:

    - Source (no cache hit): only ``sdist_root_dir`` is set.
    - Source (cache hit): both ``sdist_root_dir`` and ``cached_wheel_filename`` are set.
    - Prebuilt wheel: both ``wheel_filename`` and ``unpack_dir`` are set.
    """

    # Source path: set after download+unpack OR cache hit
    sdist_root_dir: pathlib.Path | None = None
    # Source path: set when the result came from the wheel cache
    cached_wheel_filename: pathlib.Path | None = None
    # Prebuilt path: downloaded wheel file
    wheel_filename: pathlib.Path | None = None
    # Prebuilt path: unpack directory (created by mkdir)
    unpack_dir: pathlib.Path | None = None


# Valid failure types for test mode error recording
FailureType = typing.Literal["resolution", "bootstrap", "hook", "dependency_extraction"]


class FailureRecord(typing.TypedDict):
    """Record of a package that failed during bootstrap in test mode.

    Attributes:
        package: The package name that failed.
        version: The resolved version (None if resolution failed).
        exception_type: The exception class name.
        exception_message: The exception message string.
        failure_type: Category of failure for analysis.
    """

    package: str
    version: str | None
    exception_type: str
    exception_message: str
    failure_type: FailureType


class BootstrapPhase(StrEnum):
    """Processing phases for iterative bootstrap.

    All packages: RESOLVE -> START -> ...
    Source packages: ... -> PREPARE_SOURCE -> PREPARE_BUILD -> BUILD
                     -> PROCESS_INSTALL_DEPS -> COMPLETE.
    Prebuilt packages: ... -> PREPARE_SOURCE -> PROCESS_INSTALL_DEPS -> COMPLETE.
    """

    RESOLVE = "resolve"
    START = "start"
    PREPARE_SOURCE = "prepare-source"
    PREPARE_BUILD = "prepare-build"
    BUILD = "build"
    PROCESS_INSTALL_DEPS = "process-install-deps"
    COMPLETE = "complete"
