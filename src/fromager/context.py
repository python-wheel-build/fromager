import json
import logging
import pathlib
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import settings

logger = logging.getLogger(__name__)


class WorkContext:
    def __init__(
        self,
        active_settings: settings.Settings,
        patches_dir: pathlib.Path,
        envs_dir: pathlib.Path,
        sdists_repo: pathlib.Path,
        wheels_repo: pathlib.Path,
        work_dir: pathlib.Path,
        wheel_server_url: str,
        cleanup: bool = True,
        variant: str = "cpu",
    ):
        self.settings = active_settings
        self.patches_dir = pathlib.Path(patches_dir).absolute()
        self.envs_dir = pathlib.Path(envs_dir).absolute()
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
        self.cleanup = cleanup
        self.variant = variant

        self._build_order_filename = self.work_dir / "build-order.json"
        self._constraints_filename = self.work_dir / "constraints.txt"

        # Push items onto the stack as we start to resolve their
        # dependencies so at the end we have a list of items that need to
        # be built in order.
        self._build_stack = []
        self._build_requirements = set()

        # Track requirements we've seen before so we don't resolve the
        # same dependencies over and over and so we can break cycles in
        # the dependency list. The key is the requirements spec, rather
        # than the package, in case we do have multiple rules for the same
        # package.
        self._seen_requirements = set()

    @property
    def pip_wheel_server_args(self) -> list[str]:
        args = ["--index-url", self.wheel_server_url]
        parsed = urlparse(self.wheel_server_url)
        if parsed.scheme != "https":
            args = args + ["--trusted-host", parsed.hostname]
        return args

    def _resolved_key(self, req: Requirement, version: Version) -> tuple:
        return (canonicalize_name(req.name), tuple(sorted(req.extras)), str(version))

    def mark_as_seen(self, req: Requirement, version: Version):
        key = self._resolved_key(req, version)
        logger.debug(f"{req.name}: remembering seen sdist {key}")
        self._seen_requirements.add(key)

    def has_been_seen(self, req: Requirement, version: Version) -> tuple:
        return self._resolved_key(req, version) in self._seen_requirements

    def add_to_build_order(
        self,
        req_type: str,
        req: Requirement,
        version: Version,
        why: list,
        source_url: str,
        source_url_type: str,
        prebuilt: bool = False,
    ):
        # We only care if this version of this package has been built,
        # and don't want to trigger building it twice. The "extras"
        # value, included in the _resolved_key() output, can confuse
        # that so we ignore itand build our own key using just the
        # name and version.
        key = (canonicalize_name(req.name), str(version))
        if key in self._build_requirements:
            return
        logger.info(f"{req.name}: adding {key} to build order")
        self._build_requirements.add(key)
        info = {
            "type": req_type,
            "req": str(req),
            "dist": canonicalize_name(req.name),
            "version": str(version),
            "why": why,
            "prebuilt": prebuilt,
            "source_url": source_url,
            "source_url_type": source_url_type,
        }
        self._build_stack.append(info)
        with open(self._build_order_filename, "w") as f:
            # Set default=str because the why value includes
            # Requirement and Version instances that can't be
            # converted to JSON without help.
            json.dump(self._build_stack, f, indent=2, default=str)
        with open(self._constraints_filename, "w") as f:
            for step in self._build_stack:
                f.write(f'{step["dist"]}=={step["version"]}\n')

    def setup(self):
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
        ]:
            if not p.exists():
                logger.debug("creating %s", p)
                p.mkdir(parents=True)
