"""Helpers for cloning, checking, and locating Git source trees."""

from __future__ import annotations

import logging
import pathlib
import subprocess
import typing
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import external_commands

if typing.TYPE_CHECKING:
    from fromager import context

logger = logging.getLogger(__name__)

#: Default git ref (current HEAD of the default branch)
GIT_HEAD: typing.Final = "HEAD"


def git_checkout_dir(
    *, work_dir: pathlib.Path, distribution_name: str, version: Version
) -> pathlib.Path:
    """Return the standard checkout path using the canonical distribution name.

    Args:
        work_dir: Directory that contains package work directories.
        distribution_name: Package name in any valid spelling.
        version: Resolved package version.

    Returns:
        Double-nested checkout path for the package and version.

    .. versionadded:: 0.103.0
    """
    dirname = f"{canonicalize_name(distribution_name)}-{version}"
    return work_dir / dirname / dirname


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
    ref: str = GIT_HEAD,
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


def git_clean(source_dir: pathlib.Path) -> None:
    """Remove untracked files and directories from a git working tree.

    Runs ``git clean -xdf`` in *source_dir* to remove all untracked and
    ignored files, restoring the working tree to a pristine state.

    .. versionadded:: 0.90.0
    """
    cmd: list[str] = ["git", "clean", "-xdf"]
    logger.debug("cleaning untracked files in %s", source_dir)
    external_commands.run(cmd, cwd=str(source_dir))


_GIT_STATUS_COMMAND: typing.Final = (
    "git",
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
    "--ignored=matching",
    "--ignore-submodules=none",
)


def git_checkout_changes(checkout_dir: pathlib.Path) -> str:
    """Return ``git status`` lines for local changes in a checkout.

    Lists tracked, untracked, and ignored changes in *checkout_dir* and its
    initialized submodules. Returns an empty string when there are none.
    Raises ``subprocess.CalledProcessError`` if Git cannot inspect it.

    .. versionadded:: 0.103.0
    """
    changes = external_commands.run(_GIT_STATUS_COMMAND, cwd=str(checkout_dir))
    if not changes:
        # A parent repository can hide changes inside ignored submodules.
        changes = external_commands.run(
            [
                "git",
                "submodule",
                "--quiet",
                "foreach",
                "--recursive",
                " ".join(_GIT_STATUS_COMMAND),
            ],
            cwd=str(checkout_dir),
        )
    return changes


def git_checkout_mismatch(
    *,
    checkout_dir: pathlib.Path,
    repo_url: str,
    ref: str,
) -> str | None:
    """Explain why a checkout differs from a fresh clone of *repo_url* at *ref*.

    Returns ``None`` when *checkout_dir* is the top of a Git checkout cloned
    from *repo_url*, ``HEAD`` is at *ref*, all submodules are initialized at
    their recorded commits, and there are no local changes. Otherwise returns
    a short reason. Only local state is checked, so a tag that moved on the
    remote after the clone is not detected.

    .. versionadded:: 0.103.0
    """
    if not (checkout_dir / ".git").exists():
        return "it is not a Git checkout"
    cwd = str(checkout_dir)
    try:
        # Git searches parent directories when ".git" is broken.
        toplevel = external_commands.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd
        ).strip()
        if pathlib.Path(toplevel).resolve() != checkout_dir.resolve():
            return "it is not the top of a Git checkout"
        origin = external_commands.run(
            ["git", "remote", "get-url", "origin"], cwd=cwd
        ).strip()
        if origin != repo_url:
            # Do not log URLs; they can contain credentials.
            return "it was cloned from a different repository"
        head = external_commands.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=cwd
        ).strip()
        wanted = external_commands.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=cwd
        ).strip()
        if head != wanted:
            return f"HEAD is not at {ref!r}"
        submodules = external_commands.run(
            ["git", "submodule", "status", "--recursive"], cwd=cwd
        )
        if any(line.startswith(("-", "+", "U")) for line in submodules.splitlines()):
            return "a submodule is not initialized at its recorded commit"
        if git_checkout_changes(checkout_dir):
            return "it has local changes"
    except subprocess.CalledProcessError:
        return "Git cannot inspect it"
    return None


def parse_vcs_url(vcs_url: str, *, require_ref: bool = True) -> tuple[str, str]:
    """Parse a `pip VCS URL`_ into a repo clone URL and git ref.

    Parses a string like ``git+https://github.com/python-wheel-build/fromager.git@refs/tags/0.88.0``
    into a git clone URL and git reference.

    When *require_ref* is ``False`` and the URL has no ``@ref``,
    the ref defaults to `GIT_HEAD` instead of raising an error.

    .. _pip VCS URL: https://pip.pypa.io/en/stable/topics/vcs-support/

    .. versionadded:: 0.89.0
    """
    parsed = urlparse(vcs_url)

    supported_schemes: set[str] = {"git+https", "git+ssh", "git+file"}
    if parsed.scheme not in supported_schemes:
        raise ValueError(
            f"unsupported VCS URL scheme {parsed.scheme!r},"
            f" expected one of {sorted(supported_schemes)}"
        )

    # The ref is appended to the path after the last '@'.
    path_before, sep, ref = parsed.path.rpartition("@")
    if sep and not ref:
        raise ValueError(f"VCS URL {vcs_url!r} has an empty ref after '@'")
    if not sep:
        if require_ref:
            raise ValueError(
                f"VCS URL {vcs_url!r} is missing a mandatory ref after '@'"
            )
        path_before = parsed.path
        ref = GIT_HEAD

    # Reconstruct the plain repo URL without the git+ prefix and ref
    repo_url = parsed._replace(
        scheme=parsed.scheme[4:],
        path=path_before,
        fragment="",
    ).geturl()

    return repo_url, ref
