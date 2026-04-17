import datetime
import re
import threading
import time
import typing

import pytest
import requests_mock
import resolvelib
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints, resolver
from fromager.__main__ import main as fromager
from fromager.candidate import Candidate

_hydra_core_simple_response = """
<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.1">
<title>Links for hydra-core</title>
</head>
<body>
<h1>Links for hydra-core</h1>
<a href="https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.2.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824">hydra-core-1.2.2.tar.gz</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.2.2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b" data-dist-info-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7" data-core-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7">hydra_core-1.2.2-py3-none-any.whl</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.1%2Blocal-py3-none-any.whl">hydra_core-1.3.1+local-py3-none-any.whl</a>
<br/>
<a href="https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824">hydra-core-1.3.2.tar.gz</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-1-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b" data-dist-info-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7" data-core-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7">hydra_core-1.3.2-1-py3-none-any.whl</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b" data-dist-info-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7" data-core-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7">hydra_core-1.3.2-2-py3-none-any.whl</a>
<br />
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-2.0.0a1-py3-none-any.whl" >hydra_core-2.0.0a1-py3-none-any.whl</a>
</body>
</html>
<!--SERIAL 22812307-->
"""

_numpy_simple_response = """
<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.1">
<title>Links for numpy</title>
</head>
<body>
<h1>Links for numpy</h1>
<a href="https://files.pythonhosted.org/packages/numpy-1.24.0-py3-none-any.whl">numpy-1.24.0-py3-none-any.whl</a><br/>
<a href="https://files.pythonhosted.org/packages/numpy-1.26.4-py3-none-any.whl">numpy-1.26.4-py3-none-any.whl</a><br/>
<a href="https://files.pythonhosted.org/packages/numpy-2.0.0-py3-none-any.whl">numpy-2.0.0-py3-none-any.whl</a><br/>
<a href="https://files.pythonhosted.org/packages/numpy-2.2.0-py3-none-any.whl">numpy-2.2.0-py3-none-any.whl</a><br/>
</body>
</html>
"""


@pytest.fixture(autouse=True)
def reset_cache() -> typing.Generator[None, None, None]:
    resolver.BaseProvider.clear_cache()
    yield
    resolver.BaseProvider.clear_cache()


@pytest.fixture
def pypi_hydra_resolver() -> typing.Generator[resolvelib.AbstractResolver, None, None]:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        yield resolvelib.Resolver(provider, reporter)


@pytest.fixture
def gitlab_decile_resolver() -> typing.Generator[
    resolvelib.AbstractResolver, None, None
]:
    with requests_mock.Mocker() as r:
        r.get(
            "https://gitlab.com/api/v4/projects/mirrors%2Fgithub%2Fdecile-team%2Fsubmodlib/repository/tags",
            text=_gitlab_submodlib_repo_response,
        )

        provider = resolver.GitLabTagProvider(
            project_path="mirrors/github/decile-team/submodlib",
            server_url="https://gitlab.com",
            matcher=re.compile("v(.*)"),  # with match object
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        yield resolvelib.Resolver(provider, reporter)


@pytest.fixture
def github_fromager_resolver() -> typing.Generator[
    resolvelib.AbstractResolver, None, None
]:
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider(
            organization="python-wheel-build", repo="fromager"
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        yield resolvelib.Resolver(provider, reporter)


def test_provider_choose_wheel() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-2-py3-none-any.whl"
        )
        assert str(candidate.version) == "1.3.2"


def test_provider_cache_key_pypi(pypi_hydra_resolver: typing.Any) -> None:
    req = Requirement("hydra-core<1.3")

    # fill the cache
    provider = pypi_hydra_resolver.provider
    assert provider.cache_key == "https://pypi.org/simple/"
    lock = provider._get_identifier_lock(req.name)
    with lock:
        req_cache = provider._get_cached_candidates(req.name)
    assert req_cache is None

    result = pypi_hydra_resolver.resolve([req])
    candidate = result.mapping[req.name]
    assert str(candidate.version) == "1.2.2"

    resolver_cache = resolver.BaseProvider.resolver_cache
    assert req.name in resolver_cache
    assert (resolver.PyPIProvider, provider.cache_key) in resolver_cache[req.name]
    # _get_cached_candidates returns a defensive copy, not the same object
    with lock:
        assert len(provider._get_cached_candidates(req.name)) == 7


def test_provider_cache_key_gitlab(gitlab_decile_resolver: typing.Any) -> None:
    provider = gitlab_decile_resolver.provider
    assert (
        provider.cache_key == "https://gitlab.com/mirrors/github/decile-team/submodlib"
    )


def test_provider_cache_key_github(github_fromager_resolver: typing.Any) -> None:
    provider = github_fromager_resolver.provider
    assert provider.cache_key == "python-wheel-build/fromager"


def test_cache_not_overly_aggressive() -> None:
    """Test that resolver cache doesn't poison subsequent resolutions.

    This test demonstrates the fix for issue #766 where the cache would
    store only candidates matching the first requirement's constraints,
    preventing subsequent less-constrained requirements from seeing
    newer versions.

    Scenario:
    1. First requirement: numpy<2 (e.g., from aotriton build dependency)
    2. Second requirement: numpy (e.g., from torch build dependency)

    Before the fix: Second resolution would incorrectly use numpy 1.26.4
    After the fix: Second resolution correctly uses numpy 2.2.0
    """
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/numpy/",
            text=_numpy_simple_response,
        )

        # First resolution: numpy<2 (simulating aotriton's build requirement)
        provider1 = resolver.PyPIProvider(include_sdists=False)
        reporter1: resolvelib.BaseReporter = resolvelib.BaseReporter()
        resolver1 = resolvelib.Resolver(provider1, reporter1)

        result1 = resolver1.resolve([Requirement("numpy<2")])
        candidate1 = result1.mapping["numpy"]

        assert candidate1.version == Version("1.26.4")

        # Verify cache was populated with ALL candidates (not just <2)
        cache = resolver.BaseProvider.resolver_cache
        assert "numpy" in cache
        cached_candidates = cache["numpy"][
            (resolver.PyPIProvider, "https://pypi.org/simple/")
        ]

        # Critical: Cache should have ALL 4 versions, not just the 2 that matched numpy<2
        assert len(cached_candidates) == 4
        versions = {c.version for c in cached_candidates}
        assert versions == {
            Version("1.24.0"),
            Version("1.26.4"),
            Version("2.0.0"),
            Version("2.2.0"),
        }

        # Second resolution: numpy (no constraint, simulating torch's build requirement)
        # This creates a new provider instance, but the cache is shared via the class-level
        # BaseProvider.resolver_cache, demonstrating that the cache works across instances
        provider2 = resolver.PyPIProvider(include_sdists=False)
        reporter2: resolvelib.BaseReporter = resolvelib.BaseReporter()
        resolver2 = resolvelib.Resolver(provider2, reporter2)

        result2 = resolver2.resolve([Requirement("numpy")])
        candidate2 = result2.mapping["numpy"]

        # Critical assertion: Should get latest version (2.2.0), not 1.26.4
        # This is the bug that issue #766 reported - before the fix, this would
        # incorrectly return 1.26.4 because the cache only had <2 versions
        assert candidate2.version == Version("2.2.0")

        # Verify cache is still intact with all candidates
        assert len(cached_candidates) == 4


def test_provider_choose_wheel_prereleases() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core==2.0.0a1")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-2.0.0a1-py3-none-any.whl"
        )
        assert str(candidate.version) == "2.0.0a1"


def test_provider_choose_wheel_local() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core==1.3.1+local")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.1%2Blocal-py3-none-any.whl"
        )
        assert str(candidate.version) == "1.3.1+local"


def test_provider_choose_sdist() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=False)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz"
        )
        assert str(candidate.version) == "1.3.2"


def test_provider_choose_either_with_constraint() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("hydra-core==1.3.2")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(
            include_wheels=True, include_sdists=True, constraints=constraint
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz"
            or candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-2-py3-none-any.whl"
        )


def test_provider_constraint_mismatch() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("hydra-core<=1.1")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=False, constraints=constraint)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        with pytest.raises(resolvelib.resolvers.ResolverException):
            rslvr.resolve([Requirement("hydra-core")])


def test_provider_constraint_match() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("hydra-core<=1.3")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=False, constraints=constraint)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.2.2.tar.gz"
        )
        assert str(candidate.version) == "1.2.2"


def test_pypi_provider_override_download_url() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(
            override_download_url="https://server.test/hydr_core-{version}.tar.gz"
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert candidate.url == "https://server.test/hydr_core-1.3.2.tar.gz"


_ignore_platform_simple_response = """
<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.1">
<title>Links for fromager</title>
</head>
<body>
<h1>Links for fromager</h1>
<a href="https://files.pythonhosted.org/packages/7c/06/620610984c2794ef55c4257c77211b7a625431b380880c524c2f6bc264b1/fromager-0.51.0-cp311-abi3-manylinux_2_28_plan9.whl" >fromager-0.51.0-cp311-abi3-manylinux_2_28_plan9.whl</a>
<br />
<a href="https://files.pythonhosted.org/packages/7c/06/620610984c2794ef55c4257c77211b7a625431b380880c524c2f6bc264b1/fromager-0.51.0-cp3000-abi3-manylinux_2_28_plan9.whl" >fromager-0.51.0-cp3000-abi3-manylinux_2_28_plan9.whl</a>
</body>
</html>
"""


def test_provider_platform_mismatch() -> None:
    constraint = constraints.Constraints()
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/fromager/",
            text=_ignore_platform_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=True, constraints=constraint)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        with pytest.raises(resolvelib.resolvers.ResolverException):
            rslvr.resolve([Requirement("fromager")])


def test_provider_ignore_platform() -> None:
    constraint = constraints.Constraints()
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/fromager/",
            text=_ignore_platform_simple_response,
        )

        provider = resolver.PyPIProvider(
            include_wheels=True, constraints=constraint, ignore_platform=True
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("fromager")])
        assert "fromager" in result.mapping

        candidate = result.mapping["fromager"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/7c/06/620610984c2794ef55c4257c77211b7a625431b380880c524c2f6bc264b1/fromager-0.51.0-cp311-abi3-manylinux_2_28_plan9.whl"
        )
        assert str(candidate.version) == "0.51.0"


_github_fromager_repo_response = """
{
  "id": 808690091,
  "node_id": "R_kgDOMDOhqw",
  "name": "fromager",
  "full_name": "python-wheel-build/fromager",
  "private": false,
  "owner": {
    "login": "python-wheel-build",
    "id": 171364409,
    "node_id": "O_kgDOCjbQOQ",
    "avatar_url": "https://avatars.githubusercontent.com/u/171364409?v=4",
    "gravatar_id": "",
    "url": "https://api.github.com/users/python-wheel-build",
    "html_url": "https://github.com/python-wheel-build",
    "followers_url": "https://api.github.com/users/python-wheel-build/followers",
    "following_url": "https://api.github.com/users/python-wheel-build/following{/other_user}",
    "gists_url": "https://api.github.com/users/python-wheel-build/gists{/gist_id}",
    "starred_url": "https://api.github.com/users/python-wheel-build/starred{/owner}{/repo}",
    "subscriptions_url": "https://api.github.com/users/python-wheel-build/subscriptions",
    "organizations_url": "https://api.github.com/users/python-wheel-build/orgs",
    "repos_url": "https://api.github.com/users/python-wheel-build/repos",
    "events_url": "https://api.github.com/users/python-wheel-build/events{/privacy}",
    "received_events_url": "https://api.github.com/users/python-wheel-build/received_events",
    "type": "Organization",
    "site_admin": false
  },
  "html_url": "https://github.com/python-wheel-build/fromager",
  "description": "Build your own wheels",
  "fork": false,
  "url": "https://api.github.com/repos/python-wheel-build/fromager",
  "forks_url": "https://api.github.com/repos/python-wheel-build/fromager/forks",
  "keys_url": "https://api.github.com/repos/python-wheel-build/fromager/keys{/key_id}",
  "collaborators_url": "https://api.github.com/repos/python-wheel-build/fromager/collaborators{/collaborator}",
  "teams_url": "https://api.github.com/repos/python-wheel-build/fromager/teams",
  "hooks_url": "https://api.github.com/repos/python-wheel-build/fromager/hooks",
  "issue_events_url": "https://api.github.com/repos/python-wheel-build/fromager/issues/events{/number}",
  "events_url": "https://api.github.com/repos/python-wheel-build/fromager/events",
  "assignees_url": "https://api.github.com/repos/python-wheel-build/fromager/assignees{/user}",
  "branches_url": "https://api.github.com/repos/python-wheel-build/fromager/branches{/branch}",
  "tags_url": "https://api.github.com/repos/python-wheel-build/fromager/tags",
  "blobs_url": "https://api.github.com/repos/python-wheel-build/fromager/git/blobs{/sha}",
  "git_tags_url": "https://api.github.com/repos/python-wheel-build/fromager/git/tags{/sha}",
  "git_refs_url": "https://api.github.com/repos/python-wheel-build/fromager/git/refs{/sha}",
  "trees_url": "https://api.github.com/repos/python-wheel-build/fromager/git/trees{/sha}",
  "statuses_url": "https://api.github.com/repos/python-wheel-build/fromager/statuses/{sha}",
  "languages_url": "https://api.github.com/repos/python-wheel-build/fromager/languages",
  "stargazers_url": "https://api.github.com/repos/python-wheel-build/fromager/stargazers",
  "contributors_url": "https://api.github.com/repos/python-wheel-build/fromager/contributors",
  "subscribers_url": "https://api.github.com/repos/python-wheel-build/fromager/subscribers",
  "subscription_url": "https://api.github.com/repos/python-wheel-build/fromager/subscription",
  "commits_url": "https://api.github.com/repos/python-wheel-build/fromager/commits{/sha}",
  "git_commits_url": "https://api.github.com/repos/python-wheel-build/fromager/git/commits{/sha}",
  "comments_url": "https://api.github.com/repos/python-wheel-build/fromager/comments{/number}",
  "issue_comment_url": "https://api.github.com/repos/python-wheel-build/fromager/issues/comments{/number}",
  "contents_url": "https://api.github.com/repos/python-wheel-build/fromager/contents/{+path}",
  "compare_url": "https://api.github.com/repos/python-wheel-build/fromager/compare/{base}...{head}",
  "merges_url": "https://api.github.com/repos/python-wheel-build/fromager/merges",
  "archive_url": "https://api.github.com/repos/python-wheel-build/fromager/{archive_format}{/ref}",
  "downloads_url": "https://api.github.com/repos/python-wheel-build/fromager/downloads",
  "issues_url": "https://api.github.com/repos/python-wheel-build/fromager/issues{/number}",
  "pulls_url": "https://api.github.com/repos/python-wheel-build/fromager/pulls{/number}",
  "milestones_url": "https://api.github.com/repos/python-wheel-build/fromager/milestones{/number}",
  "notifications_url": "https://api.github.com/repos/python-wheel-build/fromager/notifications{?since,all,participating}",
  "labels_url": "https://api.github.com/repos/python-wheel-build/fromager/labels{/name}",
  "releases_url": "https://api.github.com/repos/python-wheel-build/fromager/releases{/id}",
  "deployments_url": "https://api.github.com/repos/python-wheel-build/fromager/deployments",
  "created_at": "2024-05-31T15:49:02Z",
  "updated_at": "2024-06-26T14:52:13Z",
  "pushed_at": "2024-06-26T14:52:09Z",
  "git_url": "git://github.com/python-wheel-build/fromager.git",
  "ssh_url": "git@github.com:python-wheel-build/fromager.git",
  "clone_url": "https://github.com/python-wheel-build/fromager.git",
  "svn_url": "https://github.com/python-wheel-build/fromager",
  "homepage": "https://pypi.org/project/fromager/",
  "size": 907,
  "stargazers_count": 1,
  "watchers_count": 1,
  "language": "Python",
  "has_issues": true,
  "has_projects": true,
  "has_downloads": true,
  "has_wiki": false,
  "has_pages": false,
  "has_discussions": false,
  "forks_count": 4,
  "mirror_url": null,
  "archived": false,
  "disabled": false,
  "open_issues_count": 14,
  "license": {
    "key": "apache-2.0",
    "name": "Apache License 2.0",
    "spdx_id": "Apache-2.0",
    "url": "https://api.github.com/licenses/apache-2.0",
    "node_id": "MDc6TGljZW5zZTI="
  },
  "allow_forking": true,
  "is_template": false,
  "web_commit_signoff_required": false,
  "topics": [

  ],
  "visibility": "public",
  "forks": 4,
  "open_issues": 14,
  "watchers": 1,
  "default_branch": "main",
  "temp_clone_token": null,
  "custom_properties": {

  },
  "organization": {
    "login": "python-wheel-build",
    "id": 171364409,
    "node_id": "O_kgDOCjbQOQ",
    "avatar_url": "https://avatars.githubusercontent.com/u/171364409?v=4",
    "gravatar_id": "",
    "url": "https://api.github.com/users/python-wheel-build",
    "html_url": "https://github.com/python-wheel-build",
    "followers_url": "https://api.github.com/users/python-wheel-build/followers",
    "following_url": "https://api.github.com/users/python-wheel-build/following{/other_user}",
    "gists_url": "https://api.github.com/users/python-wheel-build/gists{/gist_id}",
    "starred_url": "https://api.github.com/users/python-wheel-build/starred{/owner}{/repo}",
    "subscriptions_url": "https://api.github.com/users/python-wheel-build/subscriptions",
    "organizations_url": "https://api.github.com/users/python-wheel-build/orgs",
    "repos_url": "https://api.github.com/users/python-wheel-build/repos",
    "events_url": "https://api.github.com/users/python-wheel-build/events{/privacy}",
    "received_events_url": "https://api.github.com/users/python-wheel-build/received_events",
    "type": "Organization",
    "site_admin": false
  },
  "network_count": 4,
  "subscribers_count": 1
}
"""

# This mock response text does not include the most recent release to
# ensure we're actually using the mock data.
_github_fromager_tag_response = """
[
  {
    "name": "0.9.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.9.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.9.0",
    "commit": {
      "sha": "5fbdab491e983152f7e5c8200b4f7f62f714aedf",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/5fbdab491e983152f7e5c8200b4f7f62f714aedf"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC45LjA"
  },
  {
    "name": "0.8.1",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.8.1",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.8.1",
    "commit": {
      "sha": "a790c71adeb21a02e09173407339bc25085bdf4d",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/a790c71adeb21a02e09173407339bc25085bdf4d"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC44LjE"
  },
  {
    "name": "0.8.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.8.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.8.0",
    "commit": {
      "sha": "5e3b5595d2f8751eb3ba81c287045eac85441fc3",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/5e3b5595d2f8751eb3ba81c287045eac85441fc3"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC44LjA"
  },
  {
    "name": "0.7.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.7.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.7.0",
    "commit": {
      "sha": "d97a0520a7b21bc3d0617c77da0227a4e7656be0",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/d97a0520a7b21bc3d0617c77da0227a4e7656be0"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC43LjA"
  },
  {
    "name": "0.6.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.6.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.6.0",
    "commit": {
      "sha": "7935210bb23a9fd662273dc38e98dc13f8fa3243",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/7935210bb23a9fd662273dc38e98dc13f8fa3243"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC42LjA"
  },
  {
    "name": "0.5.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.5.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.5.0",
    "commit": {
      "sha": "de945241b85ae386203383e250d3b33032f9ff4b",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/de945241b85ae386203383e250d3b33032f9ff4b"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC41LjA"
  },
  {
    "name": "0.4.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.4.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.4.0",
    "commit": {
      "sha": "b1f79701cf95c1dfb098d83438afdd66661118e3",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/b1f79701cf95c1dfb098d83438afdd66661118e3"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC40LjA"
  },
  {
    "name": "0.3.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.3.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.3.0",
    "commit": {
      "sha": "f677a155e804a5b1a4bfbf6c28773a88a6d934c6",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/f677a155e804a5b1a4bfbf6c28773a88a6d934c6"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC4zLjA"
  },
  {
    "name": "0.2.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.2.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.2.0",
    "commit": {
      "sha": "7b80c36074af597f78850eb9247d7cd1d9b27fce",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/7b80c36074af597f78850eb9247d7cd1d9b27fce"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC4yLjA"
  },
  {
    "name": "0.1.0",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.1.0",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.1.0",
    "commit": {
      "sha": "e75facfd9dd9437fa5c19badeddd6e40e9197659",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/e75facfd9dd9437fa5c19badeddd6e40e9197659"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC4xLjA"
  },
  {
    "name": "0.0.1",
    "zipball_url": "https://api.github.com/repos/python-wheel-build/fromager/zipball/refs/tags/0.0.1",
    "tarball_url": "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.0.1",
    "commit": {
      "sha": "39b0422377d0b405a8fe2ba32f384d677f1c06af",
      "url": "https://api.github.com/repos/python-wheel-build/fromager/commits/39b0422377d0b405a8fe2ba32f384d677f1c06af"
    },
    "node_id": "REF_kwDOMDOhq69yZWZzL3RhZ3MvMC4wLjE"
  }
]
"""


def test_resolve_github() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider(
            organization="python-wheel-build", repo="fromager"
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("fromager")])
        assert "fromager" in result.mapping

        candidate = result.mapping["fromager"]
        assert str(candidate.version) == "0.9.0"
        assert candidate.remote_tag == "0.9.0"
        assert candidate.remote_commit == "5fbdab491e983152f7e5c8200b4f7f62f714aedf"
        assert candidate.upload_time is None
        # check the "URL" in case tag syntax does not match version syntax
        assert (
            str(candidate.url)
            == "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.9.0"
        )


def test_resolve_github_override_download_url() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider(
            organization="python-wheel-build",
            repo="fromager",
            override_download_url="git+https://github.com/{organization}/{repo}.git@{tagname}",
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("fromager")])
        candidate = result.mapping["fromager"]
        assert (
            str(candidate.url)
            == "git+https://github.com/python-wheel-build/fromager.git@0.9.0"
        )


def test_github_constraint_mismatch() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("fromager>=1.0")
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider(
            organization="python-wheel-build", repo="fromager", constraints=constraint
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        with pytest.raises(resolvelib.resolvers.ResolverException):
            rslvr.resolve([Requirement("fromager")])


def test_github_constraint_match() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("fromager<0.9")
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider(
            organization="python-wheel-build", repo="fromager", constraints=constraint
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("fromager")])
        assert "fromager" in result.mapping

        candidate = result.mapping["fromager"]
        assert str(candidate.version) == "0.8.1"
        # check the "URL" in case tag syntax does not match version syntax
        assert (
            str(candidate.url)
            == "https://api.github.com/repos/python-wheel-build/fromager/tarball/refs/tags/0.8.1"
        )


def test_resolve_generic() -> None:
    def _versions(*args: typing.Any, **kwds: typing.Any) -> list[tuple[str, str]]:
        return [("url", "1.2"), ("url", "1.3"), ("url", "1.4.1")]

    provider = resolver.GenericProvider(version_source=_versions)
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    result = rslvr.resolve([Requirement("fromager")])
    assert "fromager" in result.mapping

    candidate = result.mapping["fromager"]
    assert str(candidate.version) == "1.4.1"

    # generic provider does not use resolver cache
    assert not resolver.BaseProvider.resolver_cache

    with pytest.raises(NotImplementedError):
        assert provider.cache_key


def test_resolve_versionmap() -> None:
    from fromager.versionmap import VersionMap

    version_map = VersionMap(
        {
            "1.2": "https://example.com/pkg-1.2.tar.gz",
            "1.3": "https://example.com/pkg-1.3.tar.gz",
            "1.4.1": "https://example.com/pkg-1.4.1.tar.gz",
        }
    )

    provider = resolver.VersionMapProvider(
        version_map=version_map, package_name="testpkg"
    )
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    result = rslvr.resolve([Requirement("testpkg")])
    assert "testpkg" in result.mapping

    candidate = result.mapping["testpkg"]
    assert str(candidate.version) == "1.4.1"
    assert candidate.url == "https://example.com/pkg-1.4.1.tar.gz"

    # VersionMapProvider uses resolver cache by default
    cache = resolver.BaseProvider.resolver_cache
    assert "testpkg" in cache
    cached_candidates = cache["testpkg"][
        (resolver.VersionMapProvider, "versionmap:testpkg")
    ]
    assert len(cached_candidates) == 3


def test_resolve_versionmap_with_constraint() -> None:
    from fromager.versionmap import VersionMap

    version_map = VersionMap(
        {
            "1.2": "https://example.com/pkg-1.2.tar.gz",
            "1.3": "https://example.com/pkg-1.3.tar.gz",
            "1.4.1": "https://example.com/pkg-1.4.1.tar.gz",
        }
    )

    c = constraints.Constraints()
    c.add_constraint("testpkg<1.4")

    provider = resolver.VersionMapProvider(
        version_map=version_map, package_name="testpkg", constraints=c
    )
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    result = rslvr.resolve([Requirement("testpkg")])
    assert "testpkg" in result.mapping

    candidate = result.mapping["testpkg"]
    assert str(candidate.version) == "1.3"
    assert candidate.url == "https://example.com/pkg-1.3.tar.gz"


def test_resolve_versionmap_no_match() -> None:
    from fromager.versionmap import VersionMap

    version_map = VersionMap(
        {
            "1.2": "https://example.com/pkg-1.2.tar.gz",
            "1.3": "https://example.com/pkg-1.3.tar.gz",
        }
    )

    provider = resolver.VersionMapProvider(
        version_map=version_map, package_name="testpkg"
    )
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    with pytest.raises(resolvelib.resolvers.ResolverException):
        rslvr.resolve([Requirement("testpkg>=2.0")])


_gitlab_submodlib_repo_response = """
[
  {
    "name": "v0.0.3",
    "message": "Version 0.0.3 release targeting specific commit",
    "target": "5d7737e306d8a266f2da162fb535f52f1570cea4",
    "commit": {
      "id": "72ae33a1ead9761e7240c2e095873047339ada7c",
      "short_id": "72ae33a1",
      "created_at": "2025-04-24T07:38:34.000-05:00",
      "parent_ids": [
        "ae066d21ec3bb92b7994e4aaede01d6e3decd177",
        "c77e898cfa5e34b8af8b545205315e221951b23a"
      ],
      "title": "Merge pull request #54 from anastasds/sampling-termination",
      "message": "Merge pull request #54 from anastasds/sampling-termination Ensure that random sampling always terminates in randomness-based optimizers",
      "author_name": "Krishnateja Killamsetty",
      "author_email": "61333497+krishnatejakk@users.noreply.github.com",
      "authored_date": "2025-04-24T07:38:34.000-05:00",
      "committer_name": "GitHub",
      "committer_email": "noreply@github.com",
      "committed_date": "2025-04-24T07:38:34.000-05:00",
      "trailers": {},
      "extended_trailers": {},
      "web_url": "https://gitlab.com/mirrors/github/decile-team/submodlib/-/commit/72ae33a1ead9761e7240c2e095873047339ada7c"
    },
    "release": null,
    "protected": false,
    "created_at": "2025-05-14T15:43:00.000Z"
  },
  {
    "name": "v0.0.2",
    "message": "",
    "target": "ae066d21ec3bb92b7994e4aaede01d6e3decd177",
    "commit": {
      "id": "ae066d21ec3bb92b7994e4aaede01d6e3decd177",
      "short_id": "ae066d21",
      "created_at": "2025-04-14T14:41:32.000-05:00",
      "parent_ids": [
        "b414069392bca65b1829caeeaea3138cfd69aa53"
      ],
      "title": "Update python-publish.yml",
      "message": "Update python-publish.yml",
      "author_name": "Krishnateja Killamsetty",
      "author_email": "61333497+krishnatejakk@users.noreply.github.com",
      "authored_date": "2025-04-14T14:41:32.000-05:00",
      "committer_name": "GitHub",
      "committer_email": "noreply@github.com",
      "committed_date": "2025-04-14T14:41:32.000-05:00",
      "trailers": {},
      "extended_trailers": {},
      "web_url": "https://gitlab.com/mirrors/github/decile-team/submodlib/-/commit/ae066d21ec3bb92b7994e4aaede01d6e3decd177"
    },
    "release": null,
    "protected": false,
    "created_at": null
  },
  {
    "name": "v0.0.1",
    "message": "Version 0.0.1 release targeting specific commit",
    "target": "e60a53f357d8851c6c61de7b0952ac04bd6415b3",
    "commit": {
      "id": "7fdc3f67c81af78554aee173ad90ee7dc9948902",
      "short_id": "7fdc3f67",
      "created_at": "2025-04-07T18:58:04.000+00:00",
      "parent_ids": [
        "d93fcdc6bb4467015a7c9375716f89ded9e466e7",
        "0db18f7f86dcf21d141da89a6e4adffc7a85d5d1"
      ],
      "title": "Merge branch 'master' of https://github.com/decile-team/submodlib",
      "message": "Merge branch 'master' of https://github.com/decile-team/submodlib",
      "author_name": "Krishnateja",
      "author_email": "krishnateja.k@ibm.com",
      "authored_date": "2025-04-07T18:58:04.000+00:00",
      "committer_name": "Krishnateja",
      "committer_email": "krishnateja.k@ibm.com",
      "committed_date": "2025-04-07T18:58:04.000+00:00",
      "trailers": {},
      "extended_trailers": {},
      "web_url": "https://gitlab.com/mirrors/github/decile-team/submodlib/-/commit/7fdc3f67c81af78554aee173ad90ee7dc9948902"
    },
    "release": null,
    "protected": false,
    "created_at": "2025-04-14T19:04:20.000Z"
  }
]
"""


def tag_match(identifier: str, item: str) -> Version | None:
    """Extract version from v-prefixed tags"""
    mo = re.match("^v(.*)$", item)
    if mo:
        try:
            return Version(mo.group(1))
        except Exception:
            pass
    return None


def test_resolve_gitlab() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://gitlab.com/api/v4/projects/mirrors%2Fgithub%2Fdecile-team%2Fsubmodlib/repository/tags",
            text=_gitlab_submodlib_repo_response,
        )

        provider = resolver.GitLabTagProvider(
            project_path="mirrors/github/decile-team/submodlib",
            server_url="https://gitlab.com",
            matcher=re.compile("v(.*)"),  # with match object
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("submodlib")])
        assert "submodlib" in result.mapping

        candidate = result.mapping["submodlib"]
        assert str(candidate.version) == "0.0.3"
        # check the "URL" in case tag syntax does not match version syntax
        assert (
            str(candidate.url)
            == "https://gitlab.com/mirrors/github/decile-team/submodlib/-/archive/v0.0.3/submodlib-v0.0.3.tar.gz"
        )
        assert candidate.remote_tag == "v0.0.3"
        assert candidate.remote_commit == "72ae33a1ead9761e7240c2e095873047339ada7c"
        assert candidate.upload_time == datetime.datetime(
            2025, 5, 14, 15, 43, 0, tzinfo=datetime.UTC
        )


def test_resolve_gitlab_override_download_url() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://gitlab.com/api/v4/projects/mirrors%2Fgithub%2Fdecile-team%2Fsubmodlib/repository/tags",
            text=_gitlab_submodlib_repo_response,
        )

        provider = resolver.GitLabTagProvider(
            project_path="mirrors/github/decile-team/submodlib",
            server_url="https://gitlab.com",
            matcher=re.compile("v(.*)"),  # with match object
            override_download_url="git+https://{hostname}/{project_path}.git@{tagname}",
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)
        result = rslvr.resolve([Requirement("submodlib")])
        candidate = result.mapping["submodlib"]
        assert (
            str(candidate.url)
            == "git+https://gitlab.com/mirrors/github/decile-team/submodlib.git@v0.0.3"
        )


def test_gitlab_constraint_mismatch() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("submodlib>=1.0")
    with requests_mock.Mocker() as r:
        r.get(
            "https://gitlab.com/api/v4/projects/mirrors%2Fgithub%2Fdecile-team%2Fsubmodlib/repository/tags",
            text=_gitlab_submodlib_repo_response,
        )

        provider = resolver.GitLabTagProvider(
            project_path="mirrors/github/decile-team/submodlib",
            server_url="https://gitlab.com",
            matcher=tag_match,  # match function
            constraints=constraint,
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        with pytest.raises(resolvelib.resolvers.ResolverException):
            rslvr.resolve([Requirement("submodlib")])


def test_gitlab_constraint_match() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("submodlib<0.0.3")
    with requests_mock.Mocker() as r:
        r.get(
            "https://gitlab.com/api/v4/projects/mirrors%2Fgithub%2Fdecile-team%2Fsubmodlib/repository/tags",
            text=_gitlab_submodlib_repo_response,
        )

        provider = resolver.GitLabTagProvider(
            project_path="mirrors/github/decile-team/submodlib",
            server_url="https://gitlab.com",
            matcher=None,  # default, Version() also ignores leading 'v'
            constraints=constraint,
        )
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("submodlib")])
        assert "submodlib" in result.mapping

        candidate = result.mapping["submodlib"]
        assert str(candidate.version) == "0.0.2"
        # check the "URL" in case tag syntax does not match version syntax
        assert (
            str(candidate.url)
            == "https://gitlab.com/mirrors/github/decile-team/submodlib/-/archive/v0.0.2/submodlib-v0.0.2.tar.gz"
        )


_response_with_data_yanked = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta name="pypi:repository-version" content="1.1">
    <title>Links for setuptools-scm</title>
</head>
<body>
    <h1>Links for setuptools-scm</h1>
    <a href="https://files.pythonhosted.org/packages/ab/ac/8f96ba9b4cfe3e4ea201f23f4f97165862395e9331a424ed325ae37024a8/setuptools_scm-8.3.1-py3-none-any.whl#sha256=332ca0d43791b818b841213e76b1971b7711a960761c5bea5fc5cdb5196fbce3">setuptools_scm-8.3.1-py3-none-any.whl</a>
    <br/>
    <a href="https://files.pythonhosted.org/packages/b9/19/7ae64b70b2429c48c3a7a4ed36f50f94687d3bfcd0ae2f152367b6410dff/setuptools_scm-8.3.1.tar.gz#sha256=3d555e92b75dacd037d32bafdf94f97af51ea29ae8c7b234cf94b7a5bd242a63">setuptools_scm-8.3.1.tar.gz</a>
    <br/>
    <a href="https://files.pythonhosted.org/packages/0c/c2/d5c5722178eb4f8d449d96dd7d6ea894fd0cb3313a24efb8bfef65fcc411/setuptools_scm-9.0.0-py3-none-any.whl#sha256=6768003ef91d3343b3f7194f911c22bcbd82ee7844e8907c5e4b35158f128b2e" data-yanked="2 unplanned regressions in config parsing and downstream api usage">setuptools_scm-9.0.0-py3-none-any.whl</a>
    <br/>
    <a href="https://files.pythonhosted.org/packages/c8/b7/7d94697d2192be602497ac82c9465496d215de7228ab4fe5c3bf641e54fb/setuptools_scm-9.0.0.tar.gz#sha256=a237477abd152e707b739fc082c9b45e1cebf3a14249de8ed4d15ee01e72c5e6" data-yanked="2 unplanned regressions in config parsing and downstream api usage">setuptools_scm-9.0.0.tar.gz</a>
</body>
</html>
"""


def test_pep592_support_latest_version_yanked() -> None:
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/setuptools-scm/", text=_response_with_data_yanked
        )

        provider = resolver.PyPIProvider()
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("setuptools-scm")])

        assert "setuptools-scm" in result.mapping

        candidate = result.mapping["setuptools-scm"]
        assert str(candidate.version) == "8.3.1"


def test_pep592_support_constraint_mismatch() -> None:
    constraint = constraints.Constraints()
    constraint.add_constraint("setuptools-scm>=9.0.0")
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/setuptools-scm/", text=_response_with_data_yanked
        )

        provider = resolver.PyPIProvider(constraints=constraint)
        reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        with pytest.raises(resolvelib.resolvers.ResolverException):
            rslvr.resolve([Requirement("setuptools-scm")])


@pytest.mark.parametrize(
    "url,filename",
    [
        ("http://example.com/path/to/file.txt", "file.txt"),
        (
            "http://localhost:8080/simple/vllm/vllm-0.10.0%2Brhai1-15-cp312-cp312-linux_x86_64.whl",
            "vllm-0.10.0+rhai1-15-cp312-cp312-linux_x86_64.whl",
        ),
    ],
)
def test_extract_filename_from_url(url: str, filename: str) -> None:
    result = resolver.extract_filename_from_url(url)
    assert result == filename


def test_custom_resolver_error_message_missing_tag() -> None:
    """Test that error message indicates custom resolver when tag doesn't exist.

    This reproduces issue #858 where the error message mentions PyPI and sdists
    even when using a custom resolver like GitHubTagProvider.
    """
    with requests_mock.Mocker() as r:
        # Mock GitHub API to return empty tags (simulating missing tag)
        r.get(
            "https://api.github.com:443/repos/test-org/test-repo/tags",
            json=[],  # Empty tags list - tag doesn't exist
        )

        provider = resolver.GitHubTagProvider(organization="test-org", repo="test-repo")

        with pytest.raises(resolvelib.resolvers.ResolverException) as exc_info:
            resolver.find_all_matching_from_provider(
                provider, Requirement("test-package==1.0.0")
            )

        error_message = str(exc_info.value)
        assert (
            "GitHub" in error_message
            or "test-org/test-repo" in error_message
            or "custom resolver" in error_message.lower()
        ), (
            f"Error message should indicate custom resolver was used (GitHub tag resolver), "
            f"but got: {error_message}"
        )
        # Should NOT mention PyPI when using GitHub resolver
        assert "pypi.org" not in error_message.lower(), (
            f"Error message incorrectly mentions PyPI when using GitHub resolver: {error_message}"
        )


def test_custom_resolver_error_message_via_resolve() -> None:
    """Test error message when using resolve() function with custom resolver override."""

    def custom_resolver_provider(
        *args: typing.Any, **kwargs: typing.Any
    ) -> resolver.GitHubTagProvider:
        """Custom resolver that returns GitHubTagProvider."""
        return resolver.GitHubTagProvider(organization="test-org", repo="test-repo")

    with requests_mock.Mocker() as r:
        # Mock GitHub API to return empty tags
        r.get(
            "https://api.github.com:443/repos/test-org/test-repo/tags",
            json=[],
        )

        provider = custom_resolver_provider()

        with pytest.raises(resolvelib.resolvers.ResolverException) as exc_info:
            resolver.find_all_matching_from_provider(
                provider, Requirement("test-package==1.0.0")
            )

        error_message = str(exc_info.value)
        # After fix for issue #858, the error message should indicate that a GitHub resolver was used
        assert (
            "GitHub" in error_message
            or "test-org/test-repo" in error_message
            or "custom resolver" in error_message.lower()
        ), f"Error message should indicate GitHub resolver was used: {error_message}"
        # Should NOT mention PyPI when using GitHub resolver
        assert "pypi.org" not in error_message.lower(), (
            f"Error message incorrectly mentions PyPI when using GitHub resolver: {error_message}"
        )


def test_cli_package_resolver(
    cli_runner: CliRunner,
    pypi_hydra_resolver: typing.Any,
) -> None:
    result = cli_runner.invoke(fromager, ["package", "resolve", "hydra-core"])
    assert result.exit_code == 0
    assert "- Fromager versions: 1.2.2, 1.3.2" in result.stdout
    assert "- PyPI versions: 1.2.2, 1.3.1+local, 1.3.2, 2.0.0a1" in result.stdout
    assert "- only wheels on PyPI: 1.3.1+local, 2.0.0a1" in result.stdout
    assert "- missing from Fromager: 1.3.1+local, 2.0.0a1" in result.stdout


def _make_candidate(name: str, version: str) -> Candidate:
    """Create a minimal Candidate for testing."""
    return Candidate(
        name=name, version=Version(version), url="https://example.com", is_sdist=False
    )


class _StubProvider(resolver.BaseProvider):
    """Minimal BaseProvider subclass for cache tests."""

    provider_description = "stub"

    @property
    def cache_key(self) -> str:
        return "stub-key"

    def find_candidates(self, identifier: str) -> list[Candidate]:
        return []


class _SlowProvider(resolver.BaseProvider):
    """BaseProvider subclass whose find_candidates delegates to a callback.

    The callback receives the identifier and can sleep, record timestamps,
    or count calls — whatever the test needs.
    """

    provider_description = "slow"

    def __init__(
        self,
        callback: typing.Callable[[str], list[Candidate]],
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(**kwargs)
        self._callback = callback

    @property
    def cache_key(self) -> str:
        return "slow-key"

    def find_candidates(self, identifier: str) -> list[Candidate]:
        return self._callback(identifier)


def test_get_cached_candidates_returns_defensive_copy() -> None:
    """Mutating the list returned by _get_cached_candidates must not corrupt the cache."""
    provider = _StubProvider()
    identifier = "test-pkg"

    # Seed the cache directly so the test doesn't depend on the aliasing bug
    resolver.BaseProvider.resolver_cache[identifier] = {
        (type(provider), provider.cache_key): [_make_candidate("test-pkg", "1.0.0")]
    }

    # Get candidates and mutate the returned list (hold the lock per the
    # documented contract, even though single-threaded)
    lock = provider._get_identifier_lock(identifier)
    with lock:
        first = provider._get_cached_candidates(identifier)
        assert first is not None
    first.append(_make_candidate("test-pkg", "2.0.0"))

    # The cache should not reflect the caller's mutation
    with lock:
        second = provider._get_cached_candidates(identifier)
        assert second is not None
    assert len(second) == 1, (
        "_get_cached_candidates should return a defensive copy, "
        "not a direct reference to the internal cache"
    )
    assert second[0].version == Version("1.0.0")


def test_find_cached_candidates_thread_safe() -> None:
    """Concurrent threads must not bypass the cache and call find_candidates multiple times."""
    call_count = 0
    call_count_lock = threading.Lock()

    def slow_find(identifier: str) -> list[Candidate]:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(0.1)
        return [_make_candidate(identifier, "1.0.0")]

    barrier = threading.Barrier(4)

    def resolve_in_thread(provider: _SlowProvider, ident: str) -> None:
        barrier.wait(timeout=5)
        list(provider._find_cached_candidates(ident))

    providers = [_SlowProvider(callback=slow_find) for _ in range(4)]
    threads = [
        threading.Thread(
            target=resolve_in_thread,
            args=(thread_provider, "shared-pkg"),
            name=f"resolver-{i}",
        )
        for i, thread_provider in enumerate(providers)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads), "Threads did not complete in time"

    assert call_count == 1, (
        f"find_candidates() was called {call_count} times; expected 1. "
        "Without thread-safe caching, multiple threads bypass the cache "
        "and redundantly call find_candidates()."
    )


def test_find_cached_candidates_different_packages_concurrent() -> None:
    """Threads resolving different packages must not block each other."""
    # Record start and end times so we can prove overlap without tight tolerances
    call_spans: dict[str, tuple[float, float]] = {}
    call_spans_lock = threading.Lock()

    def timed_find(identifier: str) -> list[Candidate]:
        start = time.monotonic()
        time.sleep(0.3)
        end = time.monotonic()
        with call_spans_lock:
            call_spans[identifier] = (start, end)
        return [_make_candidate(identifier, "1.0.0")]

    barrier = threading.Barrier(2)

    def resolve_in_thread(provider: _SlowProvider, ident: str) -> None:
        barrier.wait(timeout=5)
        list(provider._find_cached_candidates(ident))

    providers = [_SlowProvider(callback=timed_find) for _ in range(2)]
    threads = [
        threading.Thread(
            target=resolve_in_thread,
            args=(providers[i], f"pkg-{i}"),
            name=f"resolver-{i}",
        )
        for i in range(2)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads), "Threads did not complete in time"

    # Both packages should have been resolved
    assert "pkg-0" in call_spans
    assert "pkg-1" in call_spans
    # Prove concurrency: each call must have started before the other finished.
    # If a global lock serialized them, one would start only after the other ended.
    start_0, end_0 = call_spans["pkg-0"]
    start_1, end_1 = call_spans["pkg-1"]
    assert start_0 < end_1 and start_1 < end_0, (
        "find_candidates for different packages should run concurrently, "
        "not be serialized by a global lock"
    )


def test_clear_cache_cleans_up_locks() -> None:
    """clear_cache() must remove per-identifier locks so they don't accumulate."""
    provider = _StubProvider()

    # Populate the cache and create a per-identifier lock
    provider._find_cached_candidates("pkg-a")
    provider._find_cached_candidates("pkg-b")
    assert "pkg-a" in resolver.BaseProvider._cache_locks
    assert "pkg-b" in resolver.BaseProvider._cache_locks

    # Clear everything
    resolver.BaseProvider.clear_cache()
    assert resolver.BaseProvider._cache_locks == {}
    assert resolver.BaseProvider.resolver_cache == {}


def test_clear_cache_single_identifier_cleans_up_lock() -> None:
    """clear_cache(identifier) must remove only the lock for that identifier."""
    provider = _StubProvider()

    provider._find_cached_candidates("pkg-a")
    provider._find_cached_candidates("pkg-b")

    resolver.BaseProvider.clear_cache("pkg-a")
    assert "pkg-a" not in resolver.BaseProvider._cache_locks
    assert "pkg-b" in resolver.BaseProvider._cache_locks


def test_empty_candidate_list_is_cached() -> None:
    """An empty find_candidates result must be cached, not re-fetched."""
    call_count = 0

    def counting_find(identifier: str) -> list[Candidate]:
        nonlocal call_count
        call_count += 1
        return []

    provider = _SlowProvider(callback=counting_find)
    provider._find_cached_candidates("empty-pkg")
    provider._find_cached_candidates("empty-pkg")
    assert call_count == 1, (
        f"find_candidates() was called {call_count} times; expected 1. "
        "Empty candidate lists must be treated as valid cache entries."
    )


def test_find_cached_candidates_cache_disabled() -> None:
    """With use_resolver_cache=False, results must bypass the cache entirely."""
    provider = _StubProvider(use_resolver_cache=False)
    result = list(provider._find_cached_candidates("uncached-pkg"))
    assert result == []
    assert "uncached-pkg" not in resolver.BaseProvider.resolver_cache
