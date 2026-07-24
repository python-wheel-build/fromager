"""Package metadata helpers

- PEP 376 dist-info directory handling
- PEP 639-based license detection
- PEP 753 project URL normalization
"""

from .pep376 import dist_info_name, verbatim_dist_name
from .pep639 import license_from_metadata, license_from_metadata_values
from .pep753 import normalize_project_urls, project_urls_from_metadata

__all__ = (
    "dist_info_name",
    "license_from_metadata",
    "license_from_metadata_values",
    "normalize_project_urls",
    "project_urls_from_metadata",
    "verbatim_dist_name",
)
