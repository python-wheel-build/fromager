import pytest

from fromager import dependencies


@pytest.mark.parametrize(
    "build_system,expected_results",
    [
        # Empty
        ({}, dependencies._DEFAULT_BACKEND),
        # Only specify requirements (pyarrow)
        (
            {"requires": ["a-dep"]},
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
        # Specify everything
        (
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
    ],
)
def test_get_build_backend(build_system, expected_results):
    pyproject_toml = {"build-system": build_system}
    actual = dependencies.get_build_backend(pyproject_toml)
    assert expected_results == actual
