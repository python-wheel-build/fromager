import logging
import os
import pathlib
import re
import tarfile
import tempfile
import typing
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import context, external_commands, tarballs

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


class BeforeSubmoduleCallback(typing.Protocol):
    """Before submodule update callback"""

    def __call__(self, *, clonedir: pathlib.Path, name: str, remote: str) -> None:
        pass


def git_clone_and_tarball(
    *,
    destdir: pathlib.Path,
    prefix: tuple[Requirement, Version] | str,
    repo_url: str,
    tag: str | None = None,
    ref: str | None = None,
    before_submodule_update: BeforeSubmoduleCallback | None = None,
    git_archival_tag_match: str | None = None,
) -> pathlib.Path:
    """Clone a git repository and generate a ball

    This function creates a tar ball from a remote URL, with all submodules
    (non-recursive), and includes a ``.git_archival.txt`` for setuptools-scm.

    :param destdir: directory where the tar ball is stored
    :param prefix: prefix of the tar ball and first level directory
    :param repo_url: git clone url
    :param tag: tag name to clone
    :param ref: git ref to clone (mutually exclusive with *tag*)
    :param before_submodule_update: callback that runs before
        ``git submodule update``. The callback is execute for each submodule.
    :param git_archival_tag_match: git describe tag pattern for ``.git_archival.txt``

    This example code creates a ``xformers-0.0.31.post1.tar.gz`` tar ball:

    .. code-block::

       def cb(*, clonedir: pathlib.Path, name: str, remote: str) -> None:
           subprocess.check_call(
               ["git", "config", "set", f"submodule.{name}.url", mirror(remote)],
               cwd=str(clonedir)
           )

       req = Requirement("xformers")
       tag = "v0.0.31.post1"
       version = Version(tag)
       repo_url = "https://github.com/facebookresearch/xformers.git"
       destdir = pathlib.Path("destdir").absolute()
       tarball = git_clone_and_tarball(
           prefix=(req, version),
           destdir=destdir,
           repo_url=repo_url,
           tag=tag,
           before_submodule_update=cb,
       )
    """
    if isinstance(prefix, tuple):
        req = prefix[0]
        version = prefix[1]
        assert isinstance(req, Requirement)
        assert isinstance(version, Version)
        canon_name = canonicalize_name(req.name)
        prefix = f"{canon_name}-{version}"

    with tempfile.TemporaryDirectory() as tmpdir:
        clonedir = pathlib.Path(tmpdir).absolute()
        _git_clone(
            clonedir=clonedir,
            repo_url=repo_url,
            tag=tag,
            ref=ref,
        )
        submodules = _git_submodule_list(clonedir=clonedir)
        if before_submodule_update is not None:
            for name, remote in submodules.items():
                before_submodule_update(clonedir=clonedir, name=name, remote=remote)
        _get_submodule_update(clonedir=clonedir)
        _make_git_archival_txt(
            clonedir=clonedir,
            tag_match=git_archival_tag_match,
        )
        tarball = _create_tarball(
            clonedir=clonedir,
            destdir=destdir,
            prefix=prefix,
        )

    return tarball


def _git_clone(
    *,
    clonedir: pathlib.Path,
    repo_url: str,
    tag: str | None,
    ref: str | None,
) -> None:
    """Clone a git repository into *clonedir*

    Initializes submodules
    """
    if not bool(tag) ^ bool(ref):
        raise ValueError("tag and ref are mutually exclusive")

    # Create a clean URL without any credentials for logging
    parsed_url = urlparse(repo_url)
    clean_url = parsed_url._replace(netloc=parsed_url.hostname or "").geturl()
    logger.info(f"cloning {clean_url}, tag {tag}, ref {ref}, into {clonedir}")

    cmd: list[str] = ["git", "clone"]
    if tag is not None:
        # --branch works with branches and tags, but not with commits
        cmd.extend(["--branch", tag, "--depth", "1"])
    cmd.extend([repo_url, str(clonedir)])
    external_commands.run(cmd, network_isolation=False)

    # --branch only works with names, so we have to checkout the reference we
    # actually want if it is not a name
    if ref is not None:
        external_commands.run(
            ["git", "checkout", "--force", ref],
            cwd=str(clonedir),
            network_isolation=False,
        )

    # initialize submodule but do not fetch them, yet, to allow customization.
    external_commands.run(
        ["git", "submodule", "init"],
        cwd=str(clonedir),
        network_isolation=False,
    )


_SUBMODULE_RE = re.compile(r"^submodule\.(.*)\.url=(.*)$")


def _git_submodule_list(*, clonedir: pathlib.Path) -> dict[str, str]:
    """Get submodule mapping of name -> remote

    Submodule must be initialized
    """
    out = external_commands.run(
        ["git", "config", "list", "--local"],
        cwd=str(clonedir),
        network_isolation=False,
    )
    submodules = {}
    for line in out.split("\n"):
        if mo := _SUBMODULE_RE.match(line):
            name, remote = mo.groups()
            submodules[name] = remote
    logger.debug(f"found submodules: {submodules}")
    return submodules


def _get_submodule_update(*, clonedir) -> None:
    """Update and fetch submodules"""
    external_commands.run(
        ["git", "submodule", "update", "--force", "--depth", "1"],
        cwd=str(clonedir),
        network_isolation=False,
    )


def _make_git_archival_txt(
    clonedir: pathlib.Path,
    *,
    tag_match: str | None = None,
) -> str:
    """Generate a .git_archival.txt file for setuptools-scm

    https://setuptools-scm.readthedocs.io/en/latest/usage/#git-archives
    """
    if not tag_match:
        tag_match = "*[0-9]*"
    # ignore existing .git_archive.txt template
    # TODO: Figure out how to use an existing file and replace its template variables.
    archival = clonedir / ".git_archival.txt"
    parts = [
        "node: %H",  # commit hash
        "node-date: %cI",  # commit date
        f"describe-name: %(describe:tags=true,match={tag_match})",  # tag + commits since tags
    ]
    sep = "\n"  # cannot use backslash in f-strings on Python 3.11
    out = external_commands.run(
        [
            "git",
            "log",
            f"--pretty=tformat:{sep.join(parts)}",
            "-1",
        ],
        cwd=str(clonedir),
        network_isolation=False,
    )
    archival.write_text(out)
    logger.debug(f"Generated {archival} with content: \n{out}")
    return out


def _create_tarball(
    *,
    clonedir: pathlib.Path,
    destdir: pathlib.Path,
    prefix: str,
) -> pathlib.Path:
    """Create a tarball from a git checkout"""
    # check for '/' in prefix
    if os.sep in prefix:
        raise ValueError(f"{prefix=} cannot contain {os.sep}")

    tarball = destdir / f"{prefix}.tar.gz"
    if tarball.is_file():
        logger.debug(f"removing stale tar ball {tarball}")
        tarball.unlink()

    with tarfile.open(tarball, "x:gz", format=tarfile.PAX_FORMAT) as tar:
        tarballs.tar_reproducible_with_prefix(
            tar=tar,
            basedir=clonedir,
            prefix=prefix,
            exclude_vcs=True,
        )
    return tarball


def test():
    logging.basicConfig(level=logging.DEBUG)

    def cb(*, clonedir: pathlib.Path, name: str, remote: str) -> None:
        print(name, remote)

    if True:
        tag = "v0.0.31.post1"
        version = Version(tag)
        req = Requirement("xformers")
        repo_url = "https://github.com/facebookresearch/xformers.git"
    else:
        tag = "0.54.0"
        version = Version(tag)
        req = Requirement("fromager")
        repo_url = "https://github.com/python-wheel-build/fromager.git"
    destdir = pathlib.Path(".").absolute()
    tarball = git_clone_and_tarball(
        destdir=destdir,
        prefix=(req, version),
        repo_url=repo_url,
        tag=tag,
        before_submodule_update=cb,
    )
    print(tarball)


if __name__ == "__main__":
    test()
