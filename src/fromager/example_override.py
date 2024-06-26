from packaging.requirements import Requirement

from fromager import resolver


def get_resolver_provider(
    req: Requirement,
    include_sdists: bool,
    include_wheels: bool,
    sdist_server_url: str,
) -> resolver.GitHubTagProvider:
    return resolver.GitHubTagProvider(
        organization="python-wheel-build",
        repo="fromager",
    )


def expected_source_archive_name(req: Requirement, dist_version: str) -> str:
    return f"fromager-test-{dist_version}.tar.gz"


def expected_source_directory_name(req: Requirement, dist_version: str) -> str:
    return f"fromager-test-{dist_version}/different-prefix-fromager-test-{dist_version}"
