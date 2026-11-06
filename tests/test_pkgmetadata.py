import pytest
from license_expression import ExpressionError
from packaging.metadata import Metadata, RawMetadata

from fromager.pkgmetadata import (
    DeclaredLicense,
    LicenseSource,
    declared_license_from_raw_metadata,
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


BSD = "License :: OSI Approved :: BSD License"
APACHE = "License :: OSI Approved :: Apache Software License"
MIT_C = "License :: OSI Approved :: MIT License"
MPL_C = "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)"
ISC_C = "License :: OSI Approved :: ISC License (ISCL)"
LGPL3_C = "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)"
DOCUTILS_TEXT = "public domain, Python, 2-Clause BSD, GPL 3 (see COPYING.txt)"
EXPR = LicenseSource.LICENSE_EXPRESSION
CLS = LicenseSource.CLASSIFIERS
TEXT = LicenseSource.LICENSE


@pytest.mark.parametrize(
    ["license_expression", "license", "classifiers", "expected"],
    [
        # rows named after a package mirror its real wheel METADATA
        pytest.param(
            "Apache-2.0 OR BSD-2-Clause",
            None,
            None,
            DeclaredLicense(
                EXPR, "Apache-2.0 OR BSD-2-Clause", "Apache-2.0 OR BSD-2-Clause"
            ),
            id="packaging-26.3",
        ),
        pytest.param(
            "MPL-2.0 AND (Apache-2.0 OR MIT)",
            None,
            [APACHE, MIT_C],
            DeclaredLicense(
                EXPR,
                "MPL-2.0 AND (Apache-2.0 OR MIT)",
                "MPL-2.0 AND (Apache-2.0 OR MIT)",
            ),
            id="orjson-3.13.0",
        ),
        pytest.param(
            "LGPL-3.0",
            None,
            None,
            DeclaredLicense(EXPR, "LGPL-3.0", "LGPL-3.0"),
            id="expr-deprecated",
        ),
        pytest.param(
            "MIT OR LicenseRef-Proprietary",
            None,
            None,
            DeclaredLicense(
                EXPR,
                "MIT OR LicenseRef-Proprietary",
                "MIT OR LicenseRef-Proprietary",
            ),
            id="expr-licenseref",
        ),
        # expressions are canonicalized the way build backends do it
        pytest.param(
            "Apache-2.0 or mit",
            None,
            None,
            DeclaredLicense(EXPR, "Apache-2.0 or mit", "Apache-2.0 OR MIT"),
            id="expr-canonicalized",
        ),
        pytest.param(
            "GPL",
            None,
            None,
            DeclaredLicense(EXPR, "GPL", None),
            id="expr-gpl-alias",
        ),
        pytest.param(
            "Apache 2",
            None,
            [MIT_C],
            DeclaredLicense(CLS, MIT_C, "MIT"),
            id="invalid-expr-falls-through",
        ),
        pytest.param(
            "Apache 2",
            None,
            None,
            DeclaredLicense(EXPR, "Apache 2", None),
            id="invalid-expr-only",
        ),
        pytest.param(
            "MIT WITH Apache-2.0",
            None,
            None,
            DeclaredLicense(EXPR, "MIT WITH Apache-2.0", None),
            id="with-misuse",
        ),
        pytest.param(
            "  ",
            None,
            [MIT_C],
            DeclaredLicense(CLS, MIT_C, "MIT"),
            id="empty-expression",
        ),
        pytest.param(
            None,
            "MPL-2.0 AND MIT",
            [MIT_C, MPL_C],
            # two classifiers may mean a choice, so the free text decides
            DeclaredLicense(TEXT, "MPL-2.0 AND MIT", "MPL-2.0 AND MIT"),
            id="tqdm-4.66.1",
        ),
        pytest.param(
            None,
            "UNKNOWN",
            [ISC_C],
            DeclaredLicense(CLS, ISC_C, "ISC"),
            id="ptyprocess-0.7.0",
        ),
        pytest.param(
            None,
            "Apache 2.0",
            [APACHE],
            DeclaredLicense(TEXT, "Apache 2.0", "Apache-2.0"),
            id="requests-2.31.0",
        ),
        pytest.param(
            None,
            "BSD-3-Clause",
            [BSD],
            DeclaredLicense(TEXT, "BSD-3-Clause", "BSD-3-Clause"),
            id="click-8.1.7",
        ),
        pytest.param(
            None,
            "mit",
            None,
            DeclaredLicense(TEXT, "mit", "MIT"),
            id="text-lowercase-id",
        ),
        pytest.param(
            None,
            "GPL",
            None,
            DeclaredLicense(TEXT, "GPL", None),
            id="text-gpl-alias",
        ),
        pytest.param(
            None,
            "LGPL-3.0",
            [LGPL3_C],
            DeclaredLicense(TEXT, "LGPL-3.0", "LGPL-3.0"),
            id="easydict-1.13",
        ),
        pytest.param(
            None,
            "NVIDIA Proprietary Software",
            None,
            DeclaredLicense(
                TEXT,
                "NVIDIA Proprietary Software",
                "LicenseRef-NVIDIA-SOFTWARE-LICENSE",
            ),
            id="text-curated-ref",
        ),
        pytest.param(
            None,
            "Copyright (c) 2015\n        line two\n        \n        line four\n",
            None,
            DeclaredLicense(TEXT, "Copyright (c) 2015\nline two\n\nline four", None),
            id="text-folded",
        ),
        pytest.param(
            None,
            None,
            [BSD],
            DeclaredLicense(CLS, BSD, None),
            id="idna-3.6",
        ),
        pytest.param(
            None,
            None,
            [APACHE, BSD],
            DeclaredLicense(CLS, f"{APACHE}\n{BSD}", None),
            id="packaging-25.0",
        ),
        pytest.param(
            None,
            "Apache-2.0 with LLVM exception",
            [APACHE],
            DeclaredLicense(TEXT, "Apache-2.0 with LLVM exception", None),
            id="lit-18.1.8",
        ),
        pytest.param(
            None,
            DOCUTILS_TEXT,
            [
                BSD,
                "License :: OSI Approved :: GNU General Public License (GPL)",
                "License :: OSI Approved :: Python Software Foundation License",
                "License :: Public Domain",
            ],
            DeclaredLicense(TEXT, DOCUTILS_TEXT, None),
            id="docutils-0.20.1",
        ),
        pytest.param(
            None,
            None,
            ["License :: OSI Approved"],
            DeclaredLicense(CLS, "License :: OSI Approved", None),
            id="bare-osi-approved",
        ),
        # malformed expressions are rejected, not raised
        pytest.param(
            "()",
            None,
            None,
            DeclaredLicense(EXPR, "()", None),
            id="expr-parser-crash",
        ),
        pytest.param(
            None,
            "( AND LLVM-exception",
            None,
            DeclaredLicense(TEXT, "( AND LLVM-exception", None),
            id="text-parser-crash",
        ),
        pytest.param(
            None,
            None,
            [MIT_C, "License :: OSI Approved :: Python Software Foundation License"],
            DeclaredLicense(
                CLS,
                f"{MIT_C}\nLicense :: OSI Approved :: Python Software Foundation License",
                None,
            ),
            id="two-mapped-classifiers",
        ),
        pytest.param(
            None,
            None,
            [
                "License :: OSI Approved :: Nokia Open Source License",
                "License :: Nokia Open Source License (NOKOS)",
            ],
            DeclaredLicense(
                CLS,
                "License :: OSI Approved :: Nokia Open Source License\n"
                "License :: Nokia Open Source License (NOKOS)",
                "Nokia",
            ),
            id="classifiers-same-license",
        ),
        pytest.param(
            None,
            "MIT License   \n",
            None,
            DeclaredLicense(TEXT, "MIT License", "MIT"),
            id="text-trailing-whitespace",
        ),
        # license classifiers missing from the table are ambiguous
        pytest.param(
            None,
            None,
            [MIT_C, "License :: OSI Approved :: Intel Open Source License"],
            DeclaredLicense(
                CLS,
                f"{MIT_C}\nLicense :: OSI Approved :: Intel Open Source License",
                None,
            ),
            id="unknown-license-classifier",
        ),
        # classifiers that do not name a license are skipped
        pytest.param(
            None,
            None,
            [MIT_C, "License :: OSI Approved"],
            DeclaredLicense(CLS, f"{MIT_C}\nLicense :: OSI Approved", "MIT"),
            id="non-license-classifier",
        ),
        pytest.param(None, "unknown", None, None, id="unknown-only"),
        pytest.param(
            None,
            None,
            ["Programming Language :: Python :: 3"],
            None,
            id="ipadic-1.0.0",
        ),
    ],
)
def test_declared_license_from_raw_metadata(
    license_expression: str | None,
    license: str | None,
    classifiers: list[str] | None,
    expected: DeclaredLicense | None,
) -> None:
    raw = RawMetadata(metadata_version="2.4", name="test", version="1.0")
    if license_expression is not None:
        raw["license_expression"] = license_expression
    if license is not None:
        raw["license"] = license
    if classifiers is not None:
        raw["classifiers"] = classifiers

    result = declared_license_from_raw_metadata(raw)

    assert result == expected
