import pathlib
from unittest import mock

import tomlkit
from packaging.requirements import Requirement

from fromager import vendor_rust


def test_vendor_generic_rust_package_preserves_git_source_replacement(
    tmp_path: pathlib.Path,
) -> None:
    """The Cargo config redirects registry and Git dependencies to vendor."""
    manifest = tmp_path / "Cargo.toml"
    manifest.touch()
    cargo_output = f"""[source.crates-io]
replace-with = "vendored-sources"

[source."git+https://pkg.test/repository?rev=1234"]
git = "https://pkg.test/repository"
rev = "1234"
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "{tmp_path / "vendor"}"
"""

    def run_cargo(*args: object, **kwargs: object) -> str:
        vendor_dir = tmp_path / "vendor" / "dependency"
        vendor_dir.mkdir(parents=True)
        return cargo_output

    with mock.patch(
        "fromager.vendor_rust.external_commands.run", side_effect=run_cargo
    ):
        vendor_rust.vendor_generic_rust_package(
            Requirement("demo"), [manifest], tmp_path, shrink_vendored=False
        )

    config = (tmp_path / ".cargo" / "config.toml").read_text()
    assert '[source."git+https://pkg.test/repository?rev=1234"]' in config
    parsed_config = tomlkit.parse(config)
    sources = parsed_config["source"]
    git_source = sources["git+https://pkg.test/repository?rev=1234"]
    assert git_source["replace-with"] == "vendored-sources"
    assert sources["crates-io"]["replace-with"] == "vendored-sources"
    assert sources["vendored-sources"]["directory"] == "vendor"
    assert str(tmp_path) not in config
