from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import platform
import re
import subprocess
import sys
import tempfile
import typing
from email.parser import Parser
from io import TextIOWrapper

from packaging.requirements import Requirement
from packaging.tags import Tag, parse_tag
from packaging.utils import BuildTag, NormalizedName, parse_wheel_filename
from packaging.version import Version

from . import dependencies, external_commands, metrics, resolver, wheels
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


class _InstallationWheelView:
    """Reuse links within one worker, refreshing selection before each install."""

    def __init__(self, work_dir: pathlib.Path) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="install-wheels-", dir=work_dir
        )
        self.path = pathlib.Path(self._temporary.name)
        self._links: dict[str, pathlib.Path] = {}
        self._identities: dict[
            str, tuple[NormalizedName, Version, BuildTag, frozenset[Tag]]
        ] = {}

    def update(self, ctx: context.WorkContext) -> None:
        """Refresh changed links without caching settings or hook results."""
        desired: dict[str, pathlib.Path] = {}
        seen: set[str] = set()
        for source in (ctx.wheels_downloads, ctx.wheels_prebuilt):
            for path in sorted(source.glob("*.whl")):
                seen.add(path.name)
                identity = self._identities.get(path.name)
                if identity is None:
                    identity = parse_wheel_filename(path.name)
                    self._identities[path.name] = identity
                name, version, actual_tag, wheel_tags = identity
                pbi = ctx.package_build_info(name)
                if not pbi.pre_built and pbi.get_build_number(version) is not None:
                    expected = wheels.get_build_tag(
                        ctx=ctx,
                        req=Requirement(name),
                        version=version,
                        wheel_tags=wheel_tags,
                    )
                    if actual_tag != expected:
                        continue
                desired.setdefault(path.name, path)
        for filename, target in self._links.items():
            if desired.get(filename) != target:
                (self.path / filename).unlink()
        for filename, target in desired.items():
            if self._links.get(filename) != target:
                (self.path / filename).symlink_to(target)
        self._links = desired
        for filename in self._identities.keys() - seen:
            del self._identities[filename]


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
        *,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
    ):
        """Create a build environment for an sdist.

        Args:
            ctx: the work context
            req: the requirement being built
            sdist_root_dir: root directory of the unpacked sdist
        """
        self._ctx = ctx
        self._req = req
        self._sdist_root_dir = sdist_root_dir
        # abiflags adds 't' for free-threaded (nogil) builds
        self.path = sdist_root_dir.parent.absolute().joinpath(
            f"build-{platform.python_version()}{sys.abiflags}"
        )
        self._createenv()

    @property
    def sdist_root_dir(self) -> pathlib.Path:
        """Root directory of the unpacked sdist."""
        return self._sdist_root_dir

    @property
    def req(self) -> Requirement:
        """The requirement being built."""
        return self._req

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

    @contextlib.contextmanager
    def _installation_wheel_args(self, explicit: bool) -> typing.Iterator[list[str]]:
        """Expose permitted local builds, or preserve legacy source arguments."""
        if not explicit:
            yield self._ctx.pip_wheel_server_args
            return

        view: _InstallationWheelView | None = getattr(
            self._ctx._installation_wheel_views, "view", None
        )
        if view is None:
            logger.info(
                "Explicit build numbers in loaded settings enable local-only "
                "dependency installation for all packages, including unrelated "
                "versions. --wheel-server-url is not used for installation; "
                "all required wheels must be available locally."
            )
            view = _InstallationWheelView(self._ctx.work_dir)
            self._ctx._installation_wheel_views.view = view
        view.update(self._ctx)
        # uv treats build tags as preferences, not constraints. Keep other
        # builds out of its candidate set, including its installed/cache state.
        yield ["--no-index", "--offline", "--find-links", str(view.path), "--reinstall"]

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
        explicit = self._ctx.settings.has_explicit_build_numbers
        with self._installation_wheel_args(explicit) as source_args:
            cmd.extend(source_args)
            cmd.extend(str(req) for req in reqs)

            self.run(
                cmd,
                cwd=str(self.path.parent),
                network_isolation=False,
            )
        if explicit:
            self._validate_installed_build_numbers()
        logger.info(
            "installed dependencies %s into build environment in %s",
            reqs,
            self.path,
        )

    def _validate_installed_build_numbers(self) -> None:
        """Fail before compilation if direct references bypass the filtered source."""
        for name, raw_version, raw_wheel in self._installed_distributions():
            version = Version(raw_version)
            pbi = self._ctx.package_build_info(name)
            if pbi.pre_built or pbi.get_build_number(version) is None:
                continue
            metadata = Parser().parsestr(raw_wheel or "")
            tags = frozenset(
                tag for value in metadata.get_all("Tag", []) for tag in parse_tag(value)
            )
            expected = wheels.get_build_tag(
                ctx=self._ctx, req=Requirement(name), version=version, wheel_tags=tags
            )
            assert expected  # Explicit counters, including zero, are non-empty.
            expected_text = f"{expected[0]}{expected[1]}"
            match = re.fullmatch(r"([0-9]+)(.*)", metadata.get("Build") or "")
            actual: BuildTag = (int(match[1]), match[2]) if match else ()
            if not tags or actual != expected:
                raise ValueError(
                    f"{name}=={version}: installed wheel build {metadata.get('Build')!r} "
                    f"does not match explicit build {expected_text!r}"
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
        mapping = {
            name: Version(version)
            for name, version, _ in self._installed_distributions()
        }
        return dict(sorted(mapping.items()))

    def _installed_distributions(self) -> list[tuple[str, str, str | None]]:
        """Read distribution identities and wheel metadata in the build env."""
        script = (
            "import json,sys; from importlib.metadata import distributions; "
            "json.dump([(d.name, d.version, d.read_text('WHEEL')) "
            "for d in distributions()], sys.stdout)"
        )
        result = self.run([str(self.python), "-c", script])
        try:
            return typing.cast(list[tuple[str, str, str | None]], json.loads(result))
        except json.JSONDecodeError:
            logger.exception("failed to de-serialize JSON: %s", result)
            raise


@metrics.timeit(description="prepare build environment")
def prepare_build_environment(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version | None = None,
    sdist_root_dir: pathlib.Path,
) -> BuildEnvironment:
    logger.info("preparing build environment")

    build_env = BuildEnvironment(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
    )

    build_system_dependencies = dependencies.get_build_system_dependencies(
        ctx=ctx,
        req=req,
        version=version,
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
        version=version,
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
        version=version,
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

    try:
        distributions = build_env.get_distributions()
    except Exception:
        # ignore error for debug call, error reason is logged in get_distributions()
        pass
    else:
        logger.debug("build env %r has packages %r", build_env.path, distributions)

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
        logger.error(f"failed to install {dep_req_type} dependencies {deps}: {err}")
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

    logger.info("installed %s requirements %s", dep_req_type, deps)
