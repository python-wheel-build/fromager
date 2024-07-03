import logging
import os
import pathlib
import platform
import sys
import tempfile
import typing

from packaging.requirements import Requirement

from . import context, external_commands, overrides

logger = logging.getLogger(__name__)


class BuildEnvironment:
    "Wrapper for a virtualenv used for build isolation."

    def __init__(
        self,
        ctx: context.WorkContext,
        parent_dir: pathlib.Path,
        build_requirements: typing.Iterable[Requirement],
    ):
        self._ctx = ctx
        self.path = parent_dir / f"build-{platform.python_version()}"
        self._build_requirements = build_requirements
        self._createenv()

    @property
    def python(self) -> pathlib.Path:
        return (self.path / "bin/python3").absolute()

    def _createenv(self):
        if self.path.exists():
            logger.info("reusing build environment in %s", self.path)
            return

        logger.debug("creating build environment in %s", self.path)
        external_commands.run([sys.executable, "-m", "virtualenv", self.path])
        logger.info("created build environment in %s", self.path)

        req_filename = self.path / "requirements.txt"
        # FIXME: Ensure each requirement is pinned to a specific version.
        with open(req_filename, "w") as f:
            if self._build_requirements:
                for r in self._build_requirements:
                    f.write(f"{r}\n")
        if not self._build_requirements:
            return
        external_commands.run(
            [
                self.python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--only-binary",
                ":all:",
            ]
            + self._ctx.pip_wheel_server_args
            + [
                "-r",
                req_filename.absolute(),
            ],
            cwd=self.path.parent,
        )
        logger.info("installed dependencies into build environment in %s", self.path)


def build_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    build_env: BuildEnvironment,
) -> pathlib.Path | None:
    logger.info(
        f"{req.name}: building wheel for {req} in {sdist_root_dir} writing to {ctx.wheels_build}"
    )
    builder = overrides.find_override_method(req.name, "build_wheel")
    if not builder:
        builder = default_build_wheel
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    # TODO: refactor?
    # Build Rust without network access
    extra_environ["CARGO_NET_OFFLINE"] = "true"
    builder(ctx, build_env, extra_environ, req, sdist_root_dir)
    wheels = list(ctx.wheels_build.glob("*.whl"))
    if wheels:
        return wheels[0]
    return None


def default_build_wheel(
    ctx: context.WorkContext,
    build_env: BuildEnvironment,
    extra_environ: dict,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
):
    logger.debug(f"{req.name}: building wheel in {sdist_root_dir} with {extra_environ}")

    # Activate the virtualenv for the subprocess:
    # 1. Put the build environment at the front of the PATH to ensure
    #    any build tools are picked up from there and not global
    #    versions. If the caller has already set a path, start there.
    # 2. Set VIRTUAL_ENV so tools looking for that (for example,
    #    maturin) find it.
    existing_path = extra_environ.get("PATH") or os.environ.get("PATH") or ""
    path_parts = [str(build_env.python.parent)]
    if existing_path:
        path_parts.append(existing_path)
    updated_path = ":".join(path_parts)
    override_env = dict(os.environ)
    override_env.update(extra_environ)
    override_env["PATH"] = updated_path
    override_env["VIRTUAL_ENV"] = str(build_env.path)

    with tempfile.TemporaryDirectory() as dir_name:
        cmd = [
            os.fspath(build_env.python),
            "-m",
            "pip",
            "-vvv",
            "--disable-pip-version-check",
            "wheel",
            "--no-build-isolation",
            "--only-binary",
            ":all:",
            "--wheel-dir",
            os.fspath(ctx.wheels_build),
            "--no-deps",
            "--index-url",
            ctx.wheel_server_url,  # probably redundant, but just in case
            "--log",
            os.fspath(sdist_root_dir.parent / "build.log"),
            os.fspath(sdist_root_dir),
        ]
        external_commands.run(cmd, cwd=dir_name, extra_environ=override_env)
