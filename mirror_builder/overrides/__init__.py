import importlib
import importlib.util
import logging
import sys

logger = logging.getLogger(__name__)

# The interface for overriding the wheel build process is to provide a
# function build_wheel() that takes as arguments all of the same
# inputs as mirror_builder.wheels.build_wheel() and returns an
# iterable that produces the names of wheel files that were created.


def find_override_method(distname, method):
    """Given a distname and method name, look for an override implementation of the method.

    If there is no module or no method, return None.

    If the module exists and cannot be imported, propagate the exception.
    """
    module_fullname = __name__ + '.' + distname
    logger.debug('looking for %s override in %s', method, module_fullname)
    if module_fullname in sys.modules:
        mod = sys.modules[module_fullname]
    else:
        spec = importlib.util.find_spec(module_fullname)
        if spec is None:
            logger.debug('no module %s', module_fullname)
            return None
        mod = importlib.import_module(module_fullname)
    if not hasattr(mod, method):
        logger.debug('no %s override in %s', method, module_fullname)
        return None
    return getattr(mod, method)
