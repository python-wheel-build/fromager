from packaging.requirements import Requirement

from mirror_builder import sdist


def test_missing_dependency_format():
    req = Requirement('setuptools>=40.8.0')
    other_reqs = [
        Requirement('flit_core'),
        req,
    ]
    ex = sdist.MissingDependency('test', req, other_reqs)
    s = str(ex)
    # Ensure we report the thing we're actually missing
    assert 'Failed to install test dependency setuptools>=40.8.0. ' in s
    # Ensure we report what version we expected of that thing
    assert 'setuptools>=40.8.0 -> ' in s
    # Ensure we report what version we expect of all of the other dependencies
    assert 'flit_core -> ' in s
