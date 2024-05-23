import logging

from packaging.utils import canonicalize_name
from stevedore import driver

logger = logging.getLogger(__name__)

# The interface for overriding the wheel build process is to provide a
# function build_wheel() that takes as arguments all of the same
# inputs as mirror_builder.wheels.build_wheel() and returns an
# iterable that produces the names of wheel files that were created.

# Remember dists we have looked for that have no override module so we
# don't spend time trying to i mport the same missing package over and
# over.
_dists_without_overrides = set()


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
    if distname in _dists_without_overrides:
        return None

    try:
        plugin = driver.DriverManager(
            namespace='mirror_builder.project_overrides',
            name=distname,
            invoke_on_load=False,
        )
    except driver.NoMatches:
        return None
    mod = plugin.driver
    if not hasattr(mod, method):
        logger.debug('no %s override for %s', method, distname)
        return None
    return getattr(mod, method)
