import contextlib
import contextvars
import logging
import threading
import typing

from packaging.requirements import Requirement
from packaging.version import Version

TERSE_LOG_FMT = "%(asctime)s %(levelname)s %(message)s"
TERSE_DATE_FMT = "%H:%M:%S"
VERBOSE_LOG_FMT = "%(asctime)s %(levelname)s:%(name)s:%(lineno)d: %(message)s"

requirement_ctxvar: contextvars.ContextVar[Requirement] = contextvars.ContextVar(
    "requirement"
)
version_ctxvar: contextvars.ContextVar[Version] = contextvars.ContextVar("version")


@contextlib.contextmanager
def req_ctxvar_context(
    req: Requirement, version: Version | None = None
) -> typing.Generator[None, None, None]:
    """Context manager for requirement_ctxvar and version_ctxvar"""
    req_token = requirement_ctxvar.set(req)
    if version is not None:
        version_token = version_ctxvar.set(version)
    try:
        yield None
    finally:
        if version is not None:
            version_ctxvar.reset(version_token)
        requirement_ctxvar.reset(req_token)


class FromagerLogRecord(logging.LogRecord):
    """Logger record factory to add requirement and version from context var

    The class prepends f"{req.name}: " to every log message if-and-only-if
    ``requirement_ctxvar`` is set for the current context. The context var
    must be set at the beginning of a new requirement scope and reset at the
    end of a scope.

    If the ``version_ctxvar`` is also set, then the log record is prepended with
    f"{req.name}-{version}".

    ::
        for req in reqs:
            token = requirement_ctxvar.set(req)
            do_stuff(req)
            requirement_ctxvar.reset(token)
    """

    def getMessage(self) -> str:  # noqa: N802
        msg = super().getMessage()
        try:
            req = requirement_ctxvar.get()
        except LookupError:
            return msg
        else:
            try:
                version = version_ctxvar.get()
            except LookupError:
                return f"{req.name}: {msg}"
            else:
                return f"{req.name}-{version}: {msg}"


class ThreadLogFilter(logging.Filter):
    """Filter that only emits records for the given thread name"""

    def __init__(self, thread_name: str):
        self._thread_name = thread_name

    def filter(self, record: logging.LogRecord) -> bool:
        return threading.current_thread().name == self._thread_name
