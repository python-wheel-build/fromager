import contextvars
import logging

from packaging.requirements import Requirement

requirement_ctxvar: contextvars.ContextVar[Requirement] = contextvars.ContextVar(
    "requirement"
)


class FromagerLogRecord(logging.LogRecord):
    """Logger record factory to add requirement from context var

    The class prepends f"req.name: " to every log message if-and-only-if
    ``requirement_ctxvar`` is set for the current context. The context var
    must be set at the beginning of a new requirement scope and reset at the
    end of a scope.

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
            pass
        else:
            msg = f"{req.name}: {msg}"
        return msg
