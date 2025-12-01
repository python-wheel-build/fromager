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


def git_clone_fast(
    *,
    output_dir: pathlib.Path,
    repo_url: str,
    ref: str = "HEAD",
) -> None:
    """Efficient, blobless git clone with all submodules

    The function clones a git repository with submodules with a blob filter.
    A blobless clone contains the full git history but no blobs. Blobs are
    downloaded on demand. Pip's VCS feature uses similar tricks to speed
    up builds from a VCS URL.

    The *ref* parameter can be any tree-ish reference like a commit, tag, or
    branch. To force a tag, use ``refs/tags/v1.0`` to fetch the ``v1.0`` tag.

    Like in :command:`pip`, submodules are automatically cloned recursively.

    .. note::

       :command:`git` and ``libcurl`` do not support :envvar:`NETRC`. Use
       :file:`~/.netrc` or :file:`.gitconfig` for authentication.
    """
    parsed_url = urlparse(repo_url)
    # Create a clean URL without any credentials for logging
    clean_url = parsed_url._replace(netloc=parsed_url.hostname or "").geturl()
    logger.info(
        "cloning %s, tree-ish %r, into %s",
        clean_url,
        ref,
        output_dir,
    )

    # Clone repo without blobs, don't check out HEAD
    cmd: list[str]
    cmd = [
        "git",
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        repo_url,
        str(output_dir),
    ]
    external_commands.run(cmd, network_isolation=False)

    # check out reference / tag
    logger.debug("check out ref")
    cmd = [
        "git",
        "checkout",
        ref,
    ]
    external_commands.run(cmd, cwd=str(output_dir), network_isolation=False)

    # clone submodules if ".gitmodules" exist.
    if output_dir.joinpath(".gitmodules").is_file():
        # recursive clone of all submodules, filter out unnecessary blobs,
        # 4 jobs in parallel
        logger.debug("update submodules")
        cmd = [
            "git",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--filter=blob:none",
            "--jobs=4",
        ]
        external_commands.run(cmd, cwd=str(output_dir), network_isolation=False)
    else:
        logger.debug("no .gitmodules file")
