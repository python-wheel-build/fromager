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


@pytest.mark.parametrize('pkgname,expected_environ,variant', [
    ('testenv', {'FOO': '1', 'BAR': '2', 'MULTI': '-opt1=value1 -opt2=value2'}, 'test'),
    ('noexist', {}, 'test'),
    # Look for llama-cpp-python using cannonical name form. Use the
    # cuda variant file because that is the one we want to make sure
    # we can fine.
    ('llama-cpp-python', {
        'CMAKE_ARGS': '-DLLAMA_CUBLAS=on -DCMAKE_CUDA_ARCHITECTURES=all-major -DLLAMA_NATIVE=off',
        'CFLAGS': '-mno-avx',
        'FORCE_CMAKE': '1',
    }, 'cuda'),
    # Look for llama-cpp-python using non-cannonical name form. Use
    # the cuda variant file because that is the one we want to make
    # sure we can fine.
    ('llama_cpp_python', {
        'CMAKE_ARGS': '-DLLAMA_CUBLAS=on -DCMAKE_CUDA_ARCHITECTURES=all-major -DLLAMA_NATIVE=off',
        'CFLAGS': '-mno-avx',
        'FORCE_CMAKE': '1',
    }, 'cuda'),
])
def test_extra_environ_for_pkg(pkgname, expected_environ, variant):
    extra_environ = pkgs.extra_environ_for_pkg(pkgname, variant)
    assert expected_environ == extra_environ


def test_lookup_package_with_dot():
    build_wheel = pkgs.find_override_method('my.package', 'build_wheel')
    assert None is build_wheel
