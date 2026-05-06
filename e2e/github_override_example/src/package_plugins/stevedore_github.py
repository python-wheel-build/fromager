import os

from packaging.requirements import Requirement

from fromager import context, resolver


def get_resolver_provider(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool,
    include_wheels: bool,
    req_type: resolver.RequirementType | None = None,
    ignore_platform: bool = False,
) -> resolver.GitHubTagProvider:
    """Return a GitHubTagProvider for the stevedore test repo on github.com."""
    kwargs: dict[str, str] = {}
    github_api_url = os.environ.get("GITHUB_API_URL")
    if github_api_url:
        kwargs["server_url"] = github_api_url
    return resolver.GitHubTagProvider(
        organization="python-wheel-build",
        repo="stevedore-test-repo",
        constraints=ctx.constraints,
        req_type=req_type,
        override_download_url=(
            "https://github.com/{organization}/{repo}"
            "/archive/refs/tags/{tagname}.tar.gz"
        ),
        **kwargs,
    )
