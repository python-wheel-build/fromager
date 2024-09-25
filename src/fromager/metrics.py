import functools
import logging
import time
import typing
from datetime import timedelta

from packaging.requirements import Requirement
from packaging.version import Version

from . import context


def timeit(description: str) -> typing.Callable:
    def timeit_decorator(func: typing.Callable) -> typing.Callable:
        @functools.wraps(func)
        def wrapper_timeit(
            *,
            ctx: context.WorkContext,
            req: Requirement | None = None,
            **kwargs: typing.Any,
        ) -> typing.Any:
            ctx.time_description_store[func.__name__] = description

            start = time.perf_counter()
            ret = func(ctx=ctx, req=req, **kwargs)
            end = time.perf_counter()
            # get the logger for the module from which this function was called
            logger = logging.getLogger(func.__module__)
            version = (
                kwargs.get("version")
                or kwargs.get("dist_version")
                or kwargs.get("resolved_version")
            )
            if not version:
                version = _extract_version_from_return(ret)

            runtime = end - start

            if req:
                logger.debug(
                    f"{req.name}: {func.__name__} took {timedelta(seconds=runtime)} to {description}"
                )
            else:
                logger.debug(
                    f"{func.__name__} took {timedelta(seconds=runtime)} to {description}"
                )

            if req and version:
                # store total time spent calling that function for a particular version of that req
                ctx.time_store[f"{req.name}=={version}"][func.__name__] = (
                    ctx.time_store[f"{req.name}=={version}"].get(func.__name__, 0)
                    + runtime
                )

            return ret

        return wrapper_timeit

    return timeit_decorator


def summarize(ctx: context.WorkContext, prefix: str) -> None:
    logger = logging.getLogger(__name__)
    for req in sorted(ctx.time_store.keys()):
        total_time = sum(ctx.time_store[req].values())
        log = f"{prefix} {req} took {timedelta(seconds=total_time)} total"
        for fn_name, time_taken in ctx.time_store[req].items():
            log += f", {timedelta(seconds=time_taken)} to {ctx.time_description_store[fn_name]}"
        logger.info(log)


def _extract_version_from_return(ret: typing.Any) -> Version | None:
    try:
        for r in ret:
            if isinstance(r, Version):
                return r
    except Exception:
        if isinstance(ret, Version):
            return ret
    return None
