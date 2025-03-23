from packaging.version import Version


def update_local_version(old_version: Version, local_version: str | None) -> Version:
    # If we have an old local version, we append our value to it using a '.'
    # as a separator because that is the canonical separator for segments of
    # the local version string.
    if local_version is None:
        return old_version
    sep = "+" if old_version.local is None else "."
    return Version(str(old_version) + sep + local_version)
