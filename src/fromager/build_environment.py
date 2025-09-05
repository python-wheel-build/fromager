from __future__ import annotations

import json
import logging
import os
import pathlib
import platform
import re
import subprocess
import sys
import typing
from io import TextIOWrapper

from packaging.requirements import Requirement
from packaging.version import Version

from . import dependencies, external_commands, metrics, resolver
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

# uv has no API, so parse its output looking for what it couldn't install.
# Verbose regular expressions ignore blank spaces, so we have to escape those to
# have them recognized as being part of the pattern.
_uv_missing_dependency_pattern = re.compile(
    r"""(
    Because\ there\ is\ no\ version\ of\ (\w+)
    |
    Because\ you\ require\ (\w+)
    |
    Because\ (\w+)\ was\ not\ found\ in\ the\ package\ registry
    )""",
    flags=re.VERBOSE,
)


class MissingDependency(Exception):  # noqa: N818
    def __init__(
        self,
        ctx: context.WorkContext,
        req_type: RequirementType,
        req: Requirement | str | None,
        all_reqs: typing.Iterable[Requirement],
    ):
        self.all_reqs = all_reqs
        resolutions = []
        for r in all_reqs:
            try:
                _, version = resolver.resolve(
                    ctx=ctx,
                    req=r,
                    sdist_server_url=resolver.PYPI_SERVER_URL,
                    req_type=req_type,
                )
            except Exception as err:
                resolutions.append(f"{r} -> {err}")
            else:
                resolutions.append(f"{r} -> {version}")
        formatted_reqs = "\n".join(resolutions)
        if req:
            msg = (
                f"Failed to install {req_type} dependency {req}. "
                f"Check all {req_type} dependencies:\n{formatted_reqs}"
            )
        else:
            msg = (
                f"Failed to install {req_type} dependency. "
                f"Check all {req_type} dependencies:\n{formatted_reqs}"
            )
        super().__init__(f"\n{'*' * 40}\n{msg}\n{'*' * 40}\n")


class BuildEnvironment:
    """Wrapper for a virtualenv used for build isolation"""

    def __init__(
        self,
        ctx: context.WorkContext,
        parent_dir: pathlib.Path,
    ):
        self._ctx = ctx
        self.path = parent_dir.absolute() / f"build-{platform.python_version()}"
        self._createenv()

    @property
    def python(self) -> pathlib.Path:
        """Path to Python interpreter in virtual env"""
        return self.path / "bin" / "python3"

    def get_venv_environ(
        self, template_env: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Add virtual env to extra environ

        The method activates the virtualenv

        1. Put the build environment at the front of the :envvar:`PATH`
           to ensure any build tools are picked up from there and not global
           versions. If the caller has already set a path, start there.
        2. Set :envvar:`VIRTUAL_ENV` so tools looking for that (for example,
           maturin) find it.
        3. Set ``uv`` env vars.
        """
        venv_environ: dict[str, str] = {
            "VIRTUAL_ENV": str(self.path),
        }

        # pre-pend virtualenv's bin
        # 1) template_env PATH, 2) process' PATH, 3) default: "/usr/bin"
        envpath: str | None = None
        if template_env:
            envpath = template_env.get("PATH")
        if envpath is None:
            envpath = os.environ.get("PATH", "/usr/bin")
        envpath_list = envpath.split(os.pathsep)
        venv_bin = str(self.path / "bin")
        if envpath_list[0] != venv_bin:
            envpath_list.insert(0, venv_bin)
        venv_environ["PATH"] = os.pathsep.join(envpath_list)

        # uv env vars, https://docs.astral.sh/uv/reference/environment
        # custom cache for hard links and isolation from user's cache.
        venv_environ["UV_CACHE_DIR"] = str(self._ctx.uv_cache)
        # use system's trust store
        venv_environ["UV_NATIVE_TLS"] = "true"
        # don't use managed Python interpreters
        venv_environ["UV_NO_MANAGED_PYTHON"] = "true"
        venv_environ["UV_PYTHON_DOWNLOADS"] = "never"
        venv_environ["UV_PYTHON"] = str(self.python)
        # Set the maximum number of concurrent builds
        # for testing an issue with pyzmq
        venv_environ["UV_CONCURRENT_BUILDS"] = "1"
        venv_environ["UV_CONCURRENT_DOWNLOADS"] = "1"
        venv_environ["UV_CONCURRENT_INSTALLS"] = "1"

        return venv_environ

    def run(
        self,
        cmd: typing.Sequence[str],
        *,
        cwd: str | None = None,
        extra_environ: dict[str, str] | None = None,
        network_isolation: bool | None = None,
        log_filename: str | None = None,
        stdin: TextIOWrapper | None = None,
    ) -> str:
        """Run command in a virtual environment

        `network_isolation` defaults to context setting.
        """
        extra_environ = extra_environ.copy() if extra_environ else {}
        extra_environ.update(self.get_venv_environ(template_env=extra_environ))

        # default from context
        if network_isolation is None:
            network_isolation = self._ctx.network_isolation
        if network_isolation:
            # Build Rust dependencies without network access
            extra_environ.setdefault("CARGO_NET_OFFLINE", "true")

        return external_commands.run(
            cmd,
            cwd=cwd,
            extra_environ=extra_environ,
            network_isolation=network_isolation,
            log_filename=log_filename,
            stdin=stdin,
        )

    def _createenv(self) -> None:
        if self.path.exists():
            logger.info("reusing build environment in %s", self.path)
            return

        logger.debug("creating build environment in %s", self.path)

        cmd = [
            "uv",
            "venv",
            "--verbose",
            "--python",
            sys.executable,
            "--no-project",
            str(self.path),
        ]
        external_commands.run(
            cmd,
            network_isolation=self._ctx.network_isolation,
        )
        logger.info("created build environment in %s", self.path)

    def install(self, reqs: typing.Iterable[Requirement]) -> None:
        if not reqs:
            return

        # UV does not compile byte code by default
        cmd = [
            "uv",
            "pip",
            "install",
            "--verbose",
            "--upgrade",
            "--only-binary",
            ":all:",
        ]
        cmd.extend(self._ctx.pip_constraint_args)
        cmd.extend(self._ctx.pip_wheel_server_args)
        cmd.extend(str(req) for req in reqs)

        self.run(
            cmd,
            cwd=str(self.path.parent),
            network_isolation=False,
        )
        logger.info(
            "installed dependencies %s into build environment in %s",
            reqs,
            self.path,
        )

    def get_sysconfig_path(self, name: str) -> str:
        """Get ``sysconfig.get_path(name)`` in environment"""
        if not name.isidentifier():
            raise ValueError(f"{name!r} is not an identifier")
        return self.run(
            [
                str(self.python),
                "-c",
                f"import sysconfig; print(sysconfig.get_path('{name}'), end='')",
            ]
        )

    def get_distributions(self) -> typing.Mapping[str, Version]:
        """Get a mapping of installed package names and their versions in the build env"""
        lines = [
            "import sys,json",
            "from importlib.metadata import distributions",
            "json.dump({d.name: d.version for d in distributions()}, sys.stdout)",
        ]
        result = self.run([str(self.python), "-c", "; ".join(lines)])
        mapping = json.loads(result.strip())
        return {name: Version(version) for name, version in sorted(mapping.items())}

    def clean_cache(self, req: Requirement) -> None:
        """Invalidate and clean uv cache for requirement

        uv caches package metadata and unpacked wheels for faster dependency
        resolution and installation. ``uv pip install`` hardlinks files from
        cache location. This function removes a package from all caches, so
        subsequent installations use a new built.
        """
        logger.debug("invalidate uv cache for %s", req.name)
        self.run(["uv", "cache", "clean", req.name])


@metrics.timeit(description="prepare build environment")
def prepare_build_environment(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> BuildEnvironment:
    logger.info("preparing build environment")

    build_env = BuildEnvironment(
        ctx=ctx,
        parent_dir=sdist_root_dir.parent,
    )

    build_system_dependencies = dependencies.get_build_system_dependencies(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
    )
    _safe_install(
        ctx=ctx,
        req=req,
        build_env=build_env,
        deps=build_system_dependencies,
        dep_req_type=RequirementType.BUILD_SYSTEM,
    )

    build_backend_dependencies = dependencies.get_build_backend_dependencies(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_env=build_env,
    )
    _safe_install(
        ctx=ctx,
        req=req,
        build_env=build_env,
        deps=build_backend_dependencies,
        dep_req_type=RequirementType.BUILD_BACKEND,
    )

    build_sdist_dependencies = dependencies.get_build_sdist_dependencies(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_env=build_env,
    )
    _safe_install(
        ctx=ctx,
        req=req,
        build_env=build_env,
        deps=build_sdist_dependencies,
        dep_req_type=RequirementType.BUILD_SDIST,
    )

    logger.debug(
        "build env %r has packages %r", build_env.path, build_env.get_distributions()
    )

    return build_env


def _safe_install(
    ctx: context.WorkContext,
    req: Requirement,
    build_env: BuildEnvironment,
    deps: typing.Iterable[Requirement],
    dep_req_type: RequirementType,
) -> None:
    if not deps:
        return
    logger.debug("installing %s %s", dep_req_type, deps)
    try:
        build_env.install(deps)
    except subprocess.CalledProcessError as err:
        logger.error(
            f"{req.name}: failed to install {dep_req_type} dependencies {deps}: {err}"
        )
        match = _uv_missing_dependency_pattern.search(err.output)
        if match is not None:
            req_info = match.groups()[0]
        else:
            req_info = None
        raise MissingDependency(
            ctx,
            dep_req_type,
            req_info,
            deps,
        ) from err

    logger.info("%s: installed %s requirements %s", req.name, dep_req_type, deps)
