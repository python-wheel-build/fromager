"""Normalize PEP 753 project URLs

https://peps.python.org/pep-0753/
"""

import string
import typing

from packaging.metadata import Metadata

_PROJECT_URL_MAP: dict[str, str] = {
    # homepage
    "homepage": "homepage",
    # source
    "source": "source",
    "repository": "source",
    "sourcecode": "source",
    "github": "source",
    # download
    "download": "download",
    # changelog
    "changelog": "changelog",
    "changes": "changelog",
    "whatsnew": "changelog",
    "history": "changelog",
    # releasenotes
    "releasenotes": "releasenotes",
    # documentation
    "documentation": "documentation",
    "docs": "documentation",
    # issues
    "issues": "issues",
    "bugs": "issues",
    "issue": "issues",
    "tracker": "issues",
    "issuetracker": "issues",
    "bugtracker": "issues",
    # funding
    "funding": "funding",
    "sponsor": "funding",
    "donate": "funding",
    "donation": "funding",
}

_REMOVAL_MAP = str.maketrans("", "", string.punctuation + string.whitespace)


def normalize_pep753_label(label: str) -> str:
    """Normalize a label"""
    # https://peps.python.org/pep-0753/#label-normalization
    translated: str = label.strip().translate(_REMOVAL_MAP).lower()
    mapped: str | None = _PROJECT_URL_MAP.get(translated)
    if mapped is not None:
        return mapped
    return label


def normalize_project_urls(
    project_urls: typing.Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Normalize project urls

    Entries are normalized, sorted, and duplicate key/value pairs are removed.
    A key can appear multiple times, e.g. two ``homepage`` entries.
    """
    return sorted(set((normalize_pep753_label(k), v) for k, v in project_urls))


def project_urls_from_metadata(metadata: Metadata) -> list[tuple[str, str]]:
    """Get normalized project URLs from package metadata

    Takes ``project_urls``, ``home_page``, and ``download_url`` into account.
    """
    urls: list[tuple[str, str]] = []
    if metadata.project_urls:
        urls.extend(metadata.project_urls.items())
    if metadata.home_page is not None:
        urls.append(("homepage", metadata.home_page))
    if metadata.download_url is not None:
        urls.append(("download", metadata.download_url))
    return normalize_project_urls(urls)
