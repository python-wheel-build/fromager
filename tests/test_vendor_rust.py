import pathlib

from packaging.requirements import Requirement

from fromager import vendor_rust


def test_has_rust_build_backend_maturin(tmp_path: pathlib.Path) -> None:
    """Detect maturin as a Rust build backend."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[build-system]\nrequires = ["maturin>=1.0"]\nbuild-backend = "maturin"\n'
    )
    req = Requirement("some-rust-pkg")
    assert vendor_rust.has_rust_build_backend(req, tmp_path) is True


def test_has_rust_build_backend_setuptools_rust(tmp_path: pathlib.Path) -> None:
    """Detect setuptools-rust as a Rust build backend."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[build-system]\nrequires = ["setuptools", "setuptools-rust"]\n'
        'build-backend = "setuptools.build_meta"\n'
    )
    req = Requirement("some-rust-pkg")
    assert vendor_rust.has_rust_build_backend(req, tmp_path) is True


def test_has_rust_build_backend_pure_python(tmp_path: pathlib.Path) -> None:
    """Pure Python packages return False."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[build-system]\nrequires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n'
    )
    req = Requirement("pure-python-pkg")
    assert vendor_rust.has_rust_build_backend(req, tmp_path) is False


def test_has_rust_build_backend_no_pyproject(tmp_path: pathlib.Path) -> None:
    """No pyproject.toml returns False."""
    req = Requirement("legacy-pkg")
    assert vendor_rust.has_rust_build_backend(req, tmp_path) is False
