import logging
import os
import pathlib
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import (
    constraints,
    dependency_graph,
    packagesettings,
)

logger = logging.getLogger(__name__)

# Map package names to (requirement type, dependency name, version)
BuildRequirements = dict[str, list[tuple[str, NormalizedName, Version, Requirement]]]
ROOT_BUILD_REQUIREMENT = canonicalize_name("", validate=False)


class WorkContext:
    def __init__(
        self,
        active_settings: packagesettings.Settings | None,
        constraints_file: pathlib.Path | None,
        patches_dir: pathlib.Path,
        sdists_repo: pathlib.Path,
        wheels_repo: pathlib.Path,
        work_dir: pathlib.Path,
        wheel_server_url: str,
        cleanup: bool = True,
        variant: str = "cpu",
        network_isolation: bool = False,
        max_jobs: int | None = None,
        settings_dir: pathlib.Path | None = None,
    ):
        if active_settings is None:
            active_settings = packagesettings.Settings(
                settings=packagesettings.SettingsFile(),
                package_settings=[],
                patches_dir=patches_dir,
                variant=variant,
                max_jobs=max_jobs,
            )
        self.settings = active_settings
        self.input_constraints_file: pathlib.Path | None
        if constraints_file is not None:
            self.input_constraints_file = constraints_file.absolute()
            self.constraints = constraints.load(constraints_file)
        else:
            self.input_constraints_file = None
            self.constraints = constraints.Constraints({})
        self.sdists_repo = pathlib.Path(sdists_repo).absolute()
        self.sdists_downloads = self.sdists_repo / "downloads"
        self.sdists_builds = self.sdists_repo / "builds"
        self.wheels_repo = pathlib.Path(wheels_repo).absolute()
        self.wheels_build = self.wheels_repo / "build"
        self.wheels_downloads = self.wheels_repo / "downloads"
        self.wheels_prebuilt = self.wheels_repo / "prebuilt"
        self.wheel_server_dir = self.wheels_repo / "simple"
        self.work_dir = pathlib.Path(work_dir).absolute()
        self.wheel_server_url = wheel_server_url
        self.logs_dir = self.work_dir / "logs"
        self.cleanup = cleanup
        self.variant = variant
        self.network_isolation = network_isolation
        self.settings_dir = settings_dir

        self._constraints_filename = self.work_dir / "constraints.txt"

        self.dependency_graph = dependency_graph.DependencyGraph()

    @property
    def pip_wheel_server_args(self) -> list[str]:
        args = ["--index-url", self.wheel_server_url]
        parsed = urlparse(self.wheel_server_url)
        if parsed.scheme != "https" and parsed.hostname:
            args = args + ["--trusted-host", parsed.hostname]
        return args

    @property
    def pip_constraint_args(self) -> list[str]:
        if not self.input_constraints_file:
            return []
        return ["--constraint", os.fspath(self.input_constraints_file)]

    def write_to_graph_to_file(self):
        with open(self.work_dir / "graph.json", "w") as f:
            self.dependency_graph.serialize(f)

    def package_build_info(
        self, package: str | packagesettings.Package | Requirement
    ) -> packagesettings.PackageBuildInfo:
        if isinstance(package, Requirement):
            name = package.name
        else:
            name = package
        return self.settings.package_build_info(name)

    def setup(self) -> None:
        # The work dir must already exist, so don't try to create it.
        # Use os.makedirs() to create the others in case the paths
        # already exist.
        for p in [
            self.work_dir,
            self.sdists_repo,
            self.sdists_downloads,
            self.sdists_builds,
            self.wheels_repo,
            self.wheels_downloads,
            self.wheels_prebuilt,
            self.wheels_build,
            self.logs_dir,
        ]:
            if not p.exists():
                logger.debug("creating %s", p)
                p.mkdir(parents=True)
