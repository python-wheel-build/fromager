import pytest

from mirror_builder import pkgs
from mirror_builder.pkgs.overrides import flit_core


def test_flit_core_build_wheel():
    build_wheel = pkgs.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel


def test_flit_core_build_wheel_repeat():
    build_wheel = pkgs.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel
    build_wheel2 = pkgs.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel2


def test_flit_core_no_such_override():
    build_wheel = pkgs.find_override_method('flit_core', 'no_such_override')
    assert None is build_wheel


def test_nodist():
    build_wheel = pkgs.find_override_method('nodist', 'no_such_override')
    assert None is build_wheel


@pytest.mark.parametrize('dir_name,expected_patches', [
    ('clarifai-10.2.1', ['clarifai-10.2.1-fix-sdist.patch']),
    ('ninja-1.11.1.1', ['ninja-1.11.1.1-wrap-system-ninja.patch']),
    ('pytorch-v2.2.2', ['pytorch-v2.2.2-001-remove-cmake-build-requirement.patch',
                        'pytorch-v2.2.2-002-dist-info-no-run-build-deps.patch',
                        'pytorch-v2.2.2-003-fbgemm-no-maybe-uninitialized.patch',
                        'pytorch-v2.2.2-004-fix-release-version.patch']),
])
def test_patches_for_source_dir(dir_name, expected_patches):
    patches = list(pkgs.patches_for_source_dir(dir_name))
    actual_patches = [p.name for p in patches]
    assert expected_patches == actual_patches


@pytest.mark.parametrize('pkgname,expected_environ', [
    ('testenv', {'FOO': '1', 'BAR': '2'}),
    ('noexist', {}),
])
def test_extra_environ_for_pkg(pkgname, expected_environ):
    extra_environ = pkgs.extra_environ_for_pkg(pkgname)
    assert expected_environ == extra_environ


def test_lookup_package_with_dot():
    build_wheel = pkgs.find_override_method('my.package', 'build_wheel')
    assert None is build_wheel
