import pytest
from mirror_builder import pkgdb


@pytest.mark.parametrize('dir_name,expected_patches', [
    ('clarifai-10.2.1', ['clarifai-10.2.1-fix-sdist.patch']),
    ('ninja-1.11.1.1', ['ninja-1.11.1.1-wrap-system-ninja.patch']),
    ('pytorch-v2.2.2', ['pytorch-v2.2.2-0001-remove-cmake-build-requirement.patch',
                        'pytorch-v2.2.2-002-dist-info-no-run-build-deps.patch']),
])
def test_patches_for_source_dir(dir_name, expected_patches):
    patches = list(pkgdb.patches_for_source_dir(dir_name))
    actual_patches = [p.name for p in patches]
    assert expected_patches == actual_patches

@pytest.mark.parametrize('pkgname,expected_environ', [
    ('testenv', {'FOO': '1', 'BAR': '2'}),
    ('noexist', {}),
])
def test_extra_environ_for_pkg(pkgname, expected_environ):
    extra_environ = pkgdb.extra_environ_for_pkg(pkgname)
    assert expected_environ == extra_environ
