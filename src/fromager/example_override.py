from packaging.requirements import Requirement


def expected_source_archive_name(req: Requirement, dist_version: str) -> str:
    return f"fromager-test-{dist_version}.tar.gz"


def expected_source_directory_name(req: Requirement, dist_version: str) -> str:
    return f"fromager-test-{dist_version}/different-prefix-fromager-test-{dist_version}"
