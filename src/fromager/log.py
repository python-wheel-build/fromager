import contextvars
import logging
import typing

from packaging.requirements import Requirement

requirement_ctxvar: contextvars.ContextVar[Requirement] = contextvars.ContextVar(
    "requirement"
)


class LogRequirementAdapter(logging.LoggerAdapter):
    """Logger adapter to add requirement from context var

    The adapter prepends f"req.name: " to every log message if-and-only-if
    ``requirement_ctxvar`` is set for the current context. The context var
    must be set at the beginning of a new requirement scope and reset at the
    end of a scope.

    ::
        for req in reqs:
            token = requirement_ctxvar.set(req)
            do_stuff(req)
            requirement_ctxvar.reset(token)
    """

    def process(
        self, msg: str, kwargs: typing.MutableMapping[str, typing.Any]
    ) -> tuple[str, typing.MutableMapping[str, typing.Any]]:
        try:
            req = requirement_ctxvar.get()
        except LookupError:
            pass
        else:
            if "extra" in kwargs:
                kwargs["extra"] = {"req": req, **kwargs["extra"]}
            else:
                kwargs["extra"] = {"req": req}
            msg = f"{req.name}: {msg}"
        return msg, kwargs


def get_logger(name: str) -> logging.LoggerAdapter:
    """Get a custom logger instance for all Fromager modules"""
    return LogRequirementAdapter(logging.getLogger(name))
