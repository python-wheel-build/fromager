# Authentication

Fromager automatically authenticates to GitHub and GitLab APIs using
credentials from netrc or environment variables. Credentials are
resolved lazily on the first request to each host.

Authentication is recommended to avoid [API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) (especially
for GitHub) and required to access private repositories or registries.

## Credential lookup order

For each host, fromager checks the following sources in order and uses
the first match:

**GitHub** (`GITHUB_API_URL`, default `https://api.github.com`):

1. [netrc](https://docs.python.org/3/library/netrc.html) entry for
   the host -- the password is used as the token
2. `GITHUB_TOKEN` environment variable

**GitLab** (`CI_SERVER_URL`, default `https://gitlab.com`):

1. netrc entry for the host -- if the login is `gitlab-ci-token` a
   CI job token header is used, otherwise a private token header
2. `CI_JOB_TOKEN` environment variable
3. `GITLAB_PRIVATE_TOKEN` environment variable

## netrc

The [requests](https://requests.readthedocs.io) library, `pip`, and
`git` all read credentials from `~/.netrc`. Another location can be
specified by setting the `NETRC` environment variable. Note that
`git` uses libcurl for HTTPS transport and libcurl only supports the
`NETRC` variable since [8.16.0](https://curl.se/ch/8.16.0.html)
(2025-09-10). Older versions only read `$HOME/.netrc`.

For example, to authenticate to a GitLab package registry with a
[personal access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html#create-a-personal-access-token):

```text
machine gitlab.com login pat password $token
```

To authenticate to the GitHub API with a
[personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens):

```text
machine api.github.com login pat password $token
```

## Environment variables

To authenticate via environment variables instead of netrc:

```shell
# GitHub personal access token (avoids API rate limits)
export GITHUB_TOKEN=<access_token>

# GitLab CI job token (set automatically in CI pipelines)
export CI_JOB_TOKEN=<job_token>

# GitLab personal/project access token
export GITLAB_PRIVATE_TOKEN=<access_token>
```
