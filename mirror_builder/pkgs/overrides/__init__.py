import importlib
import importlib.util
import logging
import sys

from packaging.utils import canonicalize_name

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
    module_fullname = __name__ + '.' + (distname.replace('.', '_'))
    logger.debug('looking for %s override in %s', method, module_fullname)
    if module_fullname in sys.modules:
        mod = sys.modules[module_fullname]
    else:
        spec = importlib.util.find_spec(module_fullname)
        if spec is None:
            logger.debug('no module %s', module_fullname)
            _dists_without_overrides.add(distname)
            return None
        mod = importlib.import_module(module_fullname)
    if not hasattr(mod, method):
        logger.debug('no %s override in %s', method, module_fullname)
        return None
    return getattr(mod, method)
