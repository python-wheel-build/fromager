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
) -> resolver.GitLabTagProvider:
    """Return a GitLabTagProvider for the python-gitlab project on gitlab.com."""
    return resolver.GitLabTagProvider(
        project_path="python-gitlab/python-gitlab",
        constraints=ctx.constraints,
        req_type=req_type,
        cooldown=ctx.cooldown,
    )
