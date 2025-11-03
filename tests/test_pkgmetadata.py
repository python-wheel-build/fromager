import pytest
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
        [md(license="MIT License"), "MIT"],
        [md(license="MIT and PSF-2.0"), "MIT AND PSF-2.0"],
        [md(license="BSD 3-Clause License"), "BSD-3-Clause"],
        [md(classifiers=["License :: OSI Approved :: MIT License"]), "MIT"],
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
