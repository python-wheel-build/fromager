import fnmatch
import logging
from importlib import resources

from . import overrides

# An interface for reretrieving per-package information which influences
# the build process for a particular package - i.e. for a given package
# and build target, what patches should we apply, what environment variables
# should we set, etc.

logger = logging.getLogger(__name__)

find_override_method = overrides.find_override_method


def _files_for_pkg(anchor, pkg_base, ext):
    """Iterator producing files to apply to the source dir.

    Input should be the package in which to look for files, the
    pkg name as a base for matching files, and the file extension.

    Yields pathlib.Path() references to files in the order they
    are found, which is controlled through lexical sorting of
    the filenames.

    """
    # importlib.resources.files gives us back a MultiplexedPath, but
    # that doesn't support a glob() method directly, so we have to
    # look through the list of files in the path ourselves.
    files_dir = resources.files(anchor)
    pattern = pkg_base + '*' + ext
    for p in sorted(files_dir.iterdir()):
        if not fnmatch.fnmatch(p.name, '*' + ext):
            # ignore things like python files so we don't log excessively
            continue
        if not fnmatch.fnmatch(p.name, pattern):
            logger.debug(f'{p.name} does not match {pattern}')
            continue
        yield p


def patches_for_source_dir(source_dir_name):
    """Iterator producing patches to apply to the source dir.

    Input should be the base directory name, not a full path.

    Yields pathlib.Path() references to patches in the order they
    should be applied, which is controlled through lexical sorting of
    the filenames.

    """
    return _files_for_pkg('mirror_builder.pkgs.patches', source_dir_name, '.patch')


def extra_environ_for_pkg(pkgname):
    """Return a dict of extra environment variables for a particular package.

    Extra environment variables are stored in per-package .env files in the
    envs package, with a key=value per line.

    """
    extra_environ = {}
    for env_file in _files_for_pkg('mirror_builder.pkgs.envs', pkgname, '.env'):
        with open(env_file, 'r') as f:
            for line in f:
                key, value = line.strip().split('=')
                extra_environ[key] = value
    return extra_environ
