import logging

from packaging.utils import canonicalize_name
from stevedore import extension

# An interface for reretrieving per-package information which influences
# the build process for a particular package - i.e. for a given package
# and build target, what patches should we apply, what environment variables
# should we set, etc.

_mgr = extension.ExtensionManager(
    namespace='mirror_builder.project_overrides',
    invoke_on_load=False,
)


logger = logging.getLogger(__name__)


def patches_for_source_dir(patches_dir, source_dir_name):
    """Iterator producing patches to apply to the source dir.

    Input should be the base directory name, not a full path.

    Yields pathlib.Path() references to patches in the order they
    should be applied, which is controlled through lexical sorting of
    the filenames.

    """
    return patches_dir.glob(source_dir_name + '*.patch')


def extra_environ_for_pkg(envs_dir, pkgname, variant):
    """Return a dict of extra environment variables for a particular package.

    Extra environment variables are stored in per-package .env files in the
    envs package, with a key=value per line.

    """
    extra_environ = {}

    pkgname = pkgname_to_override_module(pkgname)
    variant_dir = envs_dir / variant
    env_file = variant_dir / (pkgname + '.env')

    if env_file.exists():
        logger.debug('found %s environment settings for %s in %s',
                     variant, pkgname, env_file)
        with open(env_file, 'r') as f:
            for line in f:
                key, _, value = line.strip().partition('=')
                extra_environ[key.strip()] = value.strip()
    return extra_environ


def pkgname_to_override_module(pkgname):
    canonical_name = canonicalize_name(pkgname)
    module_name = canonical_name.replace('-', '_')
    return module_name


def find_override_method(distname, method):
    """Given a distname and method name, look for an override implementation of the method.

    If there is no module or no method, return None.

    If the module exists and cannot be imported, propagate the exception.
    """
    distname = pkgname_to_override_module(distname)
    try:
        mod = _mgr[distname].plugin
    except KeyError:
        logger.debug('no override module for %s', distname)
        return None
    if not hasattr(mod, method):
        logger.debug('no %s override for %s', method, distname)
        return None
    return getattr(mod, method)
