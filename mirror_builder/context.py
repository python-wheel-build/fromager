import json
import logging
import pathlib
import platform

logger = logging.getLogger(__name__)


class WorkContext:

    def __init__(self, sdists_repo, wheels_repo, work_dir, wheel_server_port):
        self.sdists_repo = pathlib.Path(sdists_repo)
        self.sdists_downloads = self.sdists_repo / 'downloads'
        self.wheels_repo = pathlib.Path(wheels_repo)
        self.wheels_downloads = self.wheels_repo / 'downloads'
        self.wheel_server_dir = self.wheels_repo / 'simple'
        self.work_dir = pathlib.Path(work_dir)
        self.wheel_server_port = wheel_server_port

        self._build_order_filename = self.work_dir / f'build-order-{platform.python_version()}.json'

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

    def mark_as_seen(self, sdist_id):
        logger.debug('remembering seen sdist %s', sdist_id)
        self._seen_requirements.add(sdist_id)

    def has_been_seen(self, sdist_id):
        return sdist_id in self._seen_requirements

    def add_to_build_order(self, req_type, req, resolved_name, why):
        if resolved_name in self._build_requirements:
            return
        self._build_requirements.add(resolved_name)
        info = {
            'type': req_type,
            'req': str(req),
            'resolved': resolved_name,
            'why': why,
        }
        self._build_stack.append(info)
        with open(self._build_order_filename, 'w') as f:
            json.dump(self._build_stack, f, indent=2)

    def setup(self):
        # The work dir must already exist, so don't try to create it.
        # Use os.makedirs() to create the others in case the paths
        # already exist.
        for p in [self.work_dir,
                  self.sdists_repo, self.sdists_downloads,
                  self.wheels_repo, self.wheels_downloads]:
            if not p.exists():
                logger.debug('creating %s', p)
                p.mkdir(parents=True)

    @property
    def wheel_server_url(self):
        return f'http://localhost:{self.wheel_server_port}/simple/'
