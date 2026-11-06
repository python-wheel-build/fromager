import pytest
from license_expression import ExpressionError
from packaging.metadata import Metadata, RawMetadata

from fromager.pkgmetadata import (
    license_from_metadata,
    license_from_metadata_values,
    normalize_project_urls,
    project_urls_from_metadata,
)

URL = "https://home.test"
URL2 = "https://other.test"


def md(
    license_expression: str | None = None,
    license: str | None = None,
    classifiers: list[str] | None = None,
    home_page: str | None = None,
    download_url: str | None = None,
    project_urls: dict[str, str] | None = None,
) -> Metadata:
    raw = RawMetadata(
        metadata_version="2.4",
        name="test",
        version="1.0",
    )
    if license_expression is not None:
        raw["license_expression"] = license_expression
    if license is not None:
        raw["license"] = license
    if classifiers is not None:
        raw["classifiers"] = classifiers
    if home_page is not None:
        raw["home_page"] = home_page
    if download_url is not None:
        raw["download_url"] = download_url
    if project_urls is not None:
        raw["project_urls"] = project_urls
    return Metadata.from_raw(raw)


@pytest.mark.parametrize(
    ["urls", "expected"],
    [
        [{}, []],
        [{"Home-Page": URL}, [("homepage", URL)]],
        [
            {"Home-Page": URL, "homepage": URL2},
            [("homepage", URL), ("homepage", URL2)],
        ],
        [{"Home-Page": URL, "homepage": URL}, [("homepage", URL)]],
        [{"What's New?": URL}, [("changelog", URL)]],
        [{"Git Hub": URL}, [("source", URL)]],
        [{"Other Stuff": URL}, [("Other Stuff", URL)]],
    ],
)
def test_normalize_project_urls(
    urls: dict[str, str], expected: list[tuple[str, str]]
) -> None:
    assert normalize_project_urls(list(urls.items())) == expected


@pytest.mark.parametrize(
    ["metadata", "expected"],
    [
        [md(), []],
        [md(home_page=URL), [("homepage", URL)]],
        [
            md(home_page=URL, project_urls={"homepage": URL2}),
            [("homepage", URL), ("homepage", URL2)],
        ],
    ],
)
def test_project_urls_from_metadata(
    metadata: Metadata, expected: list[tuple[str, str]]
) -> None:
    assert project_urls_from_metadata(metadata) == expected


@pytest.mark.parametrize(
    ["metadata", "expected"],
    [
        [md("MIT AND MIT or MIT"), "MIT"],
        # LicenseRef is valid anywhere in a PEP 639 expression
        [md("MIT OR LicenseRef-Proprietary"), "LicenseRef-Proprietary OR MIT"],
        [md("LicenseRef-Proprietary"), "LicenseRef-Proprietary"],
        # exception keys must not be reported as unknown next to a LicenseRef
        [
            md("MIT WITH LLVM-exception OR LicenseRef-z"),
            "LicenseRef-z OR MIT WITH LLVM-exception",
        ],
        [md(license="MIT License"), "MIT"],
        [md(license="MIT and PSF-2.0"), "MIT AND PSF-2.0"],
        [md(license="BSD 3-Clause License"), "BSD-3-Clause"],
        [md(classifiers=["License :: OSI Approved :: MIT License"]), "MIT"],
        # OSI-approved zlib License, not zlib/libpng with Acknowledgement
        [md(classifiers=["License :: OSI Approved :: zlib/libpng License"]), "Zlib"],
        [
            md(
                classifiers=[
                    "License :: OSI Approved :: MIT License",
                    "License :: OSI Approved :: Python Software Foundation License",
                ]
            ),
            "MIT AND PSF-2.0",
        ],
    ],
)
def test_license_from_metadata(metadata: Metadata, expected: str) -> None:
    expr = license_from_metadata(metadata)
    assert str(expr.simplify()) == expected


@pytest.mark.parametrize(
    ["license_expression", "license", "classifiers"],
    [
        (None, None, None),
        (None, "invalid", None),
        (None, None, ["License :: OSI Approved :: BSD License"]),
        # "v3" does not say -only or -or-later, like the GPLv3 classifier
        (
            None,
            None,
            ["License :: OSI Approved :: GNU Affero General Public License v3"],
        ),
        # classifiers with no entry that maps to SPDX (see issue #1372)
        (None, None, ["Programming Language :: Python :: 3"]),
        (None, None, ["License :: OSI Approved"]),
        # non-license classifier alongside an ambiguous license classifier
        (
            None,
            None,
            [
                "Programming Language :: Python :: 3",
                "License :: OSI Approved :: BSD License",
            ],
        ),
    ],
)
def test_license_from_metadata_errors(
    license_expression: str | None,
    license: str | None,
    classifiers: list[str] | None,
) -> None:
    with pytest.raises((ValueError, ExceptionGroup)):
        license_from_metadata_values(
            license_expression=license_expression,
            license_text=license,
            classifiers=classifiers,
        )


@pytest.mark.parametrize(
    ["license_expression", "match"],
    [
        # a leading LicenseRef must not disable validation of other keys
        ("LicenseRef-Foo OR Apache 2", "Apache 2"),
        # SPDX idstrings only allow letters, digits, "." and "-"
        ("LicenseRef-a_b", "(?i)LicenseRef-a_b"),
        ("MIT WITH NotAnException", "(?i)NotAnException"),
        # PEP 639 only allows SPDX exceptions after WITH
        ("Apache-2.0 WITH LicenseRef-x", "(?i)LicenseRef-x"),
    ],
)
def test_license_from_metadata_invalid_expression(
    license_expression: str, match: str
) -> None:
    with pytest.raises(ExpressionError, match=match):
        license_from_metadata_values(license_expression=license_expression)


def test_license_from_metadata_canonicalizes_licenseref_prefix() -> None:
    # PEP 639 matches the LicenseRef- prefix case-insensitively
    expr = license_from_metadata_values(license_expression="licenseref-foo")
    assert str(expr) == "LicenseRef-foo"
