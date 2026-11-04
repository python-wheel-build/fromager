"""Map common license strings to SPDF

- https://peps.python.org/pep-0639/
- https://github.com/pypa/trove-classifiers
- https://github.com/pypa/trove-classifiers/issues/17#issuecomment-385027197
- https://spdx.org/licenses/
"""

import dataclasses
import enum
import inspect

from license_expression import ExpressionError, LicenseExpression, get_spdx_licensing
from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.metadata import Metadata, RawMetadata


def license_from_metadata(metadata: Metadata) -> LicenseExpression:
    """Detect license from packaging metadata"""
    return license_from_metadata_values(
        license_expression=metadata.license_expression,
        license_text=metadata.license,
        classifiers=metadata.classifiers,
    )


def license_from_metadata_values(
    *,
    license_expression: str | None = None,
    license_text: str | None = None,
    classifiers: list[str] | None = None,
) -> LicenseExpression:
    """Detect license from metadata values

    1. Prefer *license_expression*
    2. Fall back to *license_text*. Perform some unambiguous translatons
       (e.g. ``Apache 2`` to ``Apache-2.0``) and attempt to parse the string
       as SPDX license expression.
    3. Finally fall back to trove classifiers. Several mapped classifiers
       are joined with ``AND``; `declared_license_from_raw_metadata()`
       treats them as ambiguous instead.

    Raises an exception if license is missing, ambiguous, or not a valid
    SPDX license expression.
    """
    if not license_expression and not license_text and not classifiers:
        raise ValueError("license expression, text, and classifiers are empty")

    if license_expression:
        return _parse_spdx(license_expression)

    errors: list[Exception] = []
    if license_text:
        try:
            return _license_text_to_spdx(license_text)
        except ValueError as e:
            errors.append(e)

    if classifiers:
        try:
            return _trove_to_spdx(classifiers)
        except ValueError as e:
            errors.append(e)

    raise ExceptionGroup("unable to detect license", errors)


class LicenseSource(enum.StrEnum):
    """Core metadata field a declared license was taken from"""

    LICENSE_EXPRESSION = "License-Expression"
    CLASSIFIERS = "License classifiers"
    LICENSE = "License"


@dataclasses.dataclass(frozen=True)
class DeclaredLicense:
    """License as declared in a package's core metadata

    ``raw`` keeps the declaration (license classifiers joined by newlines)
    so it can be quoted when ``spdx`` is ``None``, which means it has no
    unambiguous SPDX mapping.
    """

    source: LicenseSource
    raw: str
    spdx: str | None


def declared_license_from_raw_metadata(
    metadata: RawMetadata,
) -> DeclaredLicense | None:
    """Detect the declared license for SBOMs without guessing

    Unlike `license_from_metadata_values()`, this never raises and reports
    an ambiguous declaration instead of guessing an SPDX id, so the caller
    can record it verbatim. Sources are tried in the order agreed in
    issue #1378: ``License-Expression``, unambiguous license classifiers,
    then free text that is an exact SPDX expression or a curated mapping.
    Without a clean mapping, the first declaration present is returned
    with ``spdx=None``, preferring free text over ambiguous classifiers
    because it is usually more specific. Classifiers that name more than
    one license are ambiguous here, while `license_from_metadata_values()`
    joins them with ``AND``.

    Returns ``None`` when the metadata declares no license at all.
    """
    expression = _declared_value(metadata.get("license_expression", "").strip())
    text = _declared_value(inspect.cleandoc(metadata.get("license", "")).strip())
    classifiers = [
        c for c in metadata.get("classifiers", []) if c.startswith("License ::")
    ]
    joined_classifiers = "\n".join(classifiers)

    canonical_expression = _canonical_spdx(expression) if expression else None
    if expression and canonical_expression:
        return DeclaredLicense(
            LicenseSource.LICENSE_EXPRESSION, expression, canonical_expression
        )
    classifier_spdx = _single_classifier_license(classifiers)
    if classifier_spdx:
        return DeclaredLicense(
            LicenseSource.CLASSIFIERS, joined_classifiers, classifier_spdx
        )
    if text:
        text_spdx = _strict_text_to_spdx(text)
        if text_spdx is not None:
            return DeclaredLicense(LicenseSource.LICENSE, text, text_spdx)

    if expression:
        return DeclaredLicense(LicenseSource.LICENSE_EXPRESSION, expression, None)
    if text:
        return DeclaredLicense(LicenseSource.LICENSE, text, None)
    if classifiers:
        return DeclaredLicense(LicenseSource.CLASSIFIERS, joined_classifiers, None)
    return None


# license classifiers that do not name a license
_NON_LICENSE_CLASSIFIERS = frozenset(
    {"License :: DFSG approved", "License :: OSI Approved"}
)


def _single_classifier_license(classifiers: list[str]) -> str | None:
    """SPDX id of the license classifiers if they name exactly one license

    Several different licenses may mean a choice (OR) or a combination
    (AND); classifiers cannot say which, so that is not guessed.
    """
    mapped: set[str] = set()
    for classifier in classifiers:
        if classifier in _NON_LICENSE_CLASSIFIERS:
            continue
        # ambiguous, or a license classifier missing from the table
        spdx = _TROVE_SPDX.get(classifier)
        if spdx is None:
            return None
        mapped.add(spdx)
    return mapped.pop() if len(mapped) == 1 else None


def _declared_value(value: str) -> str | None:
    """Treat empty values and the legacy setuptools ``UNKNOWN`` as absent"""
    if not value or value.casefold() == "unknown":
        return None
    return value


_SPDX = get_spdx_licensing()


def _parse_spdx(text: str, *, simplify: bool = False) -> LicenseExpression:
    """Parse, validate, and simplify a SPDX license expression

    `canonicalize_license_expression()` validates, so the rules match
    PEP 639 exactly (e.g. ``LicenseRef-`` anywhere, but only SPDX
    exceptions after ``WITH``); license-expression only builds the object.
    """
    try:
        canonical = canonicalize_license_expression(text)
    except InvalidLicenseExpression as err:
        raise ExpressionError(str(err)) from err
    expr = _SPDX.parse(canonical, validate=False)
    if simplify:
        expr = expr.simplify()
    return expr


def _trove_to_spdx(troves: list[str]) -> LicenseExpression:
    """Convert unambiguous trove classifiers to SPDX"""
    trove_spdx: list[str] = []
    for trove in troves:
        if trove not in _TROVE_SPDX:
            continue
        mapped: str | None = _TROVE_SPDX.get(trove)
        if mapped is None:
            raise ValueError(f"{trove!r} is ambiguous")
        trove_spdx.append(mapped)
    if not trove_spdx:
        raise ValueError("no classifier maps to a SPDX license expression")
    # join with AND
    return _parse_spdx(" AND ".join(trove_spdx), simplify=True)


def _license_text_to_spdx(text: str) -> LicenseExpression:
    """Convert unambiguous strings to SPDX"""
    text = text.strip()
    text = _LICENSE_STRING_TO_SPDX.get(text, text)
    try:
        return _parse_spdx(text)
    except Exception:
        pass
    raise ValueError(text[:100])


def _canonical_spdx(text: str) -> str | None:
    """Canonical form of a valid SPDX expression, else ``None``

    Uses the same validation build backends apply to ``License-Expression``
    (PEP 639). Unlike the license library, it rejects shorthands such as
    ``GPL`` and ``WITH`` misuse, and keeps deprecated SPDX ids as written.
    """
    try:
        return canonicalize_license_expression(text)
    except InvalidLicenseExpression:
        return None


def _strict_text_to_spdx(text: str) -> str | None:
    """Map free text only when the mapping is certain, else ``None``

    Free text must be a curated mapping or a valid SPDX expression;
    anything else would overstate what upstream declared.
    """
    if text in _LICENSE_STRING_TO_SPDX:
        return _canonical_spdx(_LICENSE_STRING_TO_SPDX[text])
    return _canonical_spdx(text)


# unambiguous text to SPDX
# The keys are common cases seen in the wild on PyPI.org
_LICENSE_STRING_TO_SPDX: dict[str, str] = {
    "http://opensource.org/licenses/MIT": "MIT",
    "MIT License": "MIT",
    "MIT license": "MIT",
    "Apache 2.0": "Apache-2.0",
    "Apache 2": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Software License 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License Version 2.0": "Apache-2.0",
    "GPLv3+": "GPL-3.0-or-later",
    "BSD 3-Clause License": "BSD-3-Clause",
    "BSD-3-Clause License": "BSD-3-Clause",
    "3-clause BSD": "BSD-3-Clause",
    "3-clause BSD License": "BSD-3-Clause",
    "ISC License": "ISC",
    "ISC license": "ISC",
    "NVIDIA Proprietary Software": "LicenseRef-NVIDIA-SOFTWARE-LICENSE",
}


# PyPA trove to SPDX
# Several trove classifiers can be mapped to an SPDX license expression. Some
# classifiers are ambiguous, e.g. 'BSD' or 'GPL'. The classifiers do not
# include license versions and extra clauses.
_TROVE_SPDX: dict[str, str | None] = {
    "License :: Aladdin Free Public License (AFPL)": "Aladdin",
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "License :: CeCILL-B Free Software License Agreement (CECILL-B)": "CECILL-B",
    "License :: CeCILL-C Free Software License Agreement (CECILL-C)": "CECILL-C",
    # not a license
    # "License :: DFSG approved": None,
    # multiple versions: EFL-1.0, EFL21.0
    "License :: Eiffel Forum License (EFL)": None,
    "License :: Free For Educational Use": None,
    "License :: Free For Home Use": None,
    "License :: Free To Use But Restricted": None,
    "License :: Free for non-commercial use": None,
    "License :: Freely Distributable": None,
    "License :: Freeware": None,
    "License :: GUST Font License 1.0": None,
    "License :: GUST Font License 2006-09-30": None,
    # multiple versions: NPL-1.0, NPL-1.1
    "License :: Netscape Public License (NPL)": None,
    "License :: Nokia Open Source License (NOKOS)": "Nokia",
    # not a license
    # "License :: OSI Approved": None,
    # multiple versions: AFL-1.1, AFL-1.2, AFL-2.0, AFL-2.1, AFL-3.0
    "License :: OSI Approved :: Academic Free License (AFL)": None,
    # multiple versions: Apache-1.0, Apache-1.1, Apache-2.0
    "License :: OSI Approved :: Apache Software License": None,
    # multiple versions: APSL-1.0, APSL-1.1, APSL-1.2, APSL-2.0
    "License :: OSI Approved :: Apple Public Source License": None,
    # multiple versions: Artistic-1.0, Artistic-2.0
    "License :: OSI Approved :: Artistic License": None,
    "License :: OSI Approved :: Attribution Assurance License": "AAL",
    # multiple versions and extra clauses
    "License :: OSI Approved :: BSD License": None,
    "License :: OSI Approved :: Blue Oak Model License (BlueOak-1.0.0)": "BlueOak-1.0.0",
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "License :: OSI Approved :: CEA CNRS Inria Logiciel Libre License, version 2.1 (CeCILL-2.1)": "CeCILL-2.1",
    "License :: OSI Approved :: CMU License (MIT-CMU)": "MIT-CMU",
    "License :: OSI Approved :: Common Development and Distribution License 1.0 (CDDL-1.0)": "CDDL-1.0",
    "License :: OSI Approved :: Common Public License": "CPL-1.0",
    "License :: OSI Approved :: Eclipse Public License 1.0 (EPL-1.0)": "EPL-1.0",
    "License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "License :: OSI Approved :: Educational Community License, Version 2.0 (ECL-2.0)": "ECL-2.0",
    # multiple versions
    "License :: OSI Approved :: Eiffel Forum License": None,
    "License :: OSI Approved :: European Union Public Licence 1.0 (EUPL 1.0)": "EUPL-1.0",
    "License :: OSI Approved :: European Union Public Licence 1.1 (EUPL 1.1)": "EUPL-1.1",
    "License :: OSI Approved :: European Union Public Licence 1.2 (EUPL 1.2)": "EUPL-1.2",
    # ambiguous, see PEP 639
    "License :: OSI Approved :: GNU Affero General Public License v3": None,
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    # multiple versions
    "License :: OSI Approved :: GNU Free Documentation License (FDL)": None,
    # multiple versions
    "License :: OSI Approved :: GNU General Public License (GPL)": None,
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": None,
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": None,
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": None,
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": None,
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": None,
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    # ambigious, see PEP 639
    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)": None,
    # multiple versions
    "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)": None,
    "License :: OSI Approved :: IBM Public License": "IPL-1.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: MirOS License (MirOS)": "MirOS",
    "License :: OSI Approved :: Motosoto License": "Motosoto",
    "License :: OSI Approved :: Mozilla Public License 1.0 (MPL)": "MPL-1.0",
    "License :: OSI Approved :: Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Mulan Permissive Software License v2 (MulanPSL-2.0)": "MulanPSL-2.0",
    "License :: OSI Approved :: NASA Open Source Agreement v1.3 (NASA-1.3)": "NASA-1.3",
    "License :: OSI Approved :: Nethack General Public License": "NGPL",
    "License :: OSI Approved :: Nokia Open Source License": "Nokia",
    "License :: OSI Approved :: Open Group Test Suite License": "OGTSL",
    "License :: OSI Approved :: Open Software License 3.0 (OSL-3.0)": "OSL-3.0",
    "License :: OSI Approved :: PostgreSQL License": "PostgreSQL",
    "License :: OSI Approved :: Python License (CNRI Python License)": "CNRI-Python",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Qt Public License (QPL)": "QPL-1.0",
    "License :: OSI Approved :: Ricoh Source Code Public License": "RSCPL",
    "License :: OSI Approved :: SIL Open Font License 1.1 (OFL-1.1)": "OFL-1.1",
    "License :: OSI Approved :: Sleepycat License": "Sleepycat",
    "License :: OSI Approved :: Sun Public License": "SPL-1.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: Universal Permissive License (UPL)": "UPL-1.0",
    "License :: OSI Approved :: University of Illinois/NCSA Open Source License": "NCSA",
    "License :: OSI Approved :: Vovida Software License 1.0": "VSL-1.0",
    "License :: OSI Approved :: W3C License": "W3C",
    "License :: OSI Approved :: Zero-Clause BSD (0BSD)": "0BSD",
    # multiple versions: ZPL-1.1, ZPL-2.0, ZPL-2.1
    "License :: OSI Approved :: Zope Public License": None,
    # zlib-acknowledgement is a different license that is not OSI approved
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
    "License :: Other/Proprietary License": None,
    "License :: Public Domain": None,
    "License :: Repoze Public License": None,
}
