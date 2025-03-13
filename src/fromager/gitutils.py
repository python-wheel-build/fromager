import logging
import pathlib
from urllib.parse import urlparse

from packaging.requirements import Requirement

from fromager import context, external_commands

logger = logging.getLogger(__name__)


def git_clone(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    output_dir: pathlib.Path,
    repo_url: str,
    tag: str | None = None,
    ref: str | None = None,
    submodules: bool | list[str] = False,
) -> pathlib.Path:
    """Clone a git repository"""
    if tag is not None and ref is not None:
        raise ValueError("tag and ref are mutually exclusive")

    # Create a clean URL without any credentials for logging
    parsed_url = urlparse(repo_url)
    clean_url = parsed_url._replace(netloc=parsed_url.hostname or "").geturl()
    logger.info(
        "%s: cloning %s, tag %r, ref %r, submodules %r, into %s",
        req.name,
        clean_url,
        tag,
        ref,
        submodules,
        output_dir,
    )
    cmd: list[str] = ["git", "clone"]
    if tag is not None:
        # --branch works with branches and tags, but not with commits
        cmd.extend(["--branch", tag, "--depth", "1"])
    if submodules:
        if isinstance(submodules, list):
            for pathspec in submodules:
                cmd.append(f"--recurse-submodules={pathspec}")
        else:
            # all submodules
            cmd.append("--recurse-submodules")
        if tag is not None:
            cmd.append("--shallow-submodules")
    cmd.extend([repo_url, str(output_dir)])
    external_commands.run(cmd, network_isolation=False)

    # --branch only works with names, so we have to checkout the reference we
    # actually want if it is not a name
    if ref is not None:
        external_commands.run(
            ["git", "checkout", "--recurse-submodules", "--force", ref],
            cwd=str(output_dir),
            network_isolation=False,
        )

    return output_dir
