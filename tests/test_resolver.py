import requests_mock
import resolvelib
from packaging.requirements import Requirement

from fromager import resolver

_hydra_core_simple_response = """
<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.1">
<title>Links for hydra-core</title>
</head>
<body>
<h1>Links for hydra-core</h1>
<a href="https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824">hydra-core-1.3.2.tar.gz</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b" data-dist-info-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7" data-core-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7">hydra_core-1.3.2-py3-none-any.whl</a>
<br/>
</body>
</html>
<!--SERIAL 22812307-->
"""


def test_provider_choose_wheel():
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b"
        )
        assert str(candidate.version) == "1.3.2"


def test_provider_choose_sdist():
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=False)
        reporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824"
        )
        assert str(candidate.version) == "1.3.2"


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


def test_resolve_github():
    with requests_mock.Mocker() as r:
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager",
            text=_github_fromager_repo_response,
        )
        r.get(
            "https://api.github.com:443/repos/python-wheel-build/fromager/tags",
            text=_github_fromager_tag_response,
        )

        provider = resolver.GitHubTagProvider("python-wheel-build", "fromager")
        reporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("fromager")])
        assert "fromager" in result.mapping

        candidate = result.mapping["fromager"]
        assert str(candidate.version) == "0.9.0"
        # check the "URL" in case tag syntax does not match version syntax
        assert str(candidate.url) == "0.9.0"
