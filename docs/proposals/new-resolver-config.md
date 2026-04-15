# New resolver and download configuration

- Author: Christian Heimes
- Created: 2026-02-24
- Status: Open

## What

This enhancement document proposes a new approach to configure the package
resolver and source / sdist downloader. The new settings are covering a
wider range of use cases. Common patterns like building a package from a
git checkout will no longer need custom Python plugins.

## Why

In downstream, we are encountering an increasing amount of packages that do
not build from sdists on PyPI. Either package maintainers are not uploading
source distributions to PyPI or sdists have issues. In some cases, packages
use a midstream fork that is not on PyPI. The sources need to be build from
git.

Because Fromager \<= 0.76 does not have declarative settings for GitHub/GitLab
resolver or cloning git repositories, we have to write custom Python plugins.
The plugins are a maintenance burden.

## Goals

- support common use cases with package settings instead of custom plugin code
- cover most common resolver scenarios:
  - resolve package on PyPI (sdist, wheel, or both)
  - resolve package on GitHub or GitLab with custom tag matcher
- cover common sdist download and build scenarios:
  - sdist from PyPI
  - prebuilt wheel from PyPI
  - download tarball from URL
  - clone git repository
  - download an artifact from GitHub / GitLab release or tag
  - build sdist with PEP 517 hook or plain tarball
- support per-variant setting, e.g. one variant uses prebuilt wheel while the
  rest uses sdist.
- gradual migration path from old system to new configuration

## Non-goals

- The new system will not cover all use cases. Some specific use cases will
  still require custom code.
- Retrieval of additional sources is out of scope, e.g. a package `egg` that
  needs `libegg-{version}.tar.gz`.
- Provide SSH transport for git. The feature can be added at a later point
  when it's needed.
- Extra options for authentication. The `requests` library and `git` CLI can
  use `$HOME/.netrc` for authentication.
  > **NOTE:** `requests` also supports `NETRC` environment variable,
  > `libcurl` and therefore `git` did not support `NETRC` before
  > libcurl [8.16.0](https://curl.se/ch/8.16.0.html) (2025-09-10). Before
  > `git` _only_ supports `$HOME/.netrc`.

## How

The new system will use a new top-level configuration key `source`. The old
`download_source` and `resolver_dist` settings will stay supported for a
while. Eventually the old options will be deprecated and removed.

In addition to a top-level `source` entry, the resolver and downloader can
be overwritten in a variant `source` entry. This enables variant-specific
settings. For example a package resolve and download from GitHub and one
variant uses a pre-built wheel from a custom index.

Each use case is handled a provider profile. The profile name acts as a tag
([discriminated union](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions)).
Each use case has a well-defined set of mandatory and optional arguments.

**Example:**

```yaml
source:
  # `pypi-sdist` is the default provider
  provider: pypi-sdist
variants:
  egg:
    source:
      # resolve and download prebuilt wheel
      provider: pypi-prebuilt
      index_url: https://custom-index.example/simple
  spam:
    source:
        # resolve tag on GitLab, clone tag over https, build an sdist with PEP 517 hook
        provider: gitlab-tag-git
        project_url: https://gitlab.example/spam/spam
        matcher_factory: package_plugins.matchers:midstream_matcher_factory
        build_sdist: pep517
  viking:
    source:
        # resolve on PyPI, git clone, and build as tarball
        provider: pypi-git
        clone_url: https://git.example/viking/viking.git
        tag: 'v{version}'
        build_sdist: tarball
  caerbannog:
    # resolve with a mapping of version number to git refs, git clone, and build with PEP 517 hook
    source:
      provider: versionmap-git
      clone_url: https://git.example/viking/viking.git
      build_sdist: pep517
      versionmap:
        '1.0': abad1dea
        '1.1': refs/tags/1.1
  camelot:
    source:
      # On second thought, let's not go to Camelot. It is a silly place.
      provider: not-available
```

### Profiles

- The `pypi-sdist` profile resolve versions on PyPI or PyPI-compatible index.
  It only takes sdists into account and downloads the sdist from the index.
  The profile is equivalent to the current default settings with
  `include_sdists: true` and `include_wheels: false`.

- The `pypi-prebuilt` profile resolve versions of platform-specific wheels
  on PyPI and downloads the pre-built wheel. The profile is equivalent to
  `include_sdists: false`, `include_wheels: true`, and variant setting
  `pre_build: true`.

- The `pypi-download` resolve versions of any package on PyPI and downloads
  a tarball from an external URL (with `{version}` variable in download URL).
  It takes any sdist and any wheel into account. The profile is equivalent
  with `include_sdists: true`, `include_wheels: true`, `ignore_platform: true`,
  and a `download_source.url`.

- The `pypi-git` is similar to the `pypi-download` profile. Instead of
  downloading a tarball, it clones a git repository at a specific tag.

- The `versionmap-git` profiles maps known version numbers to known git
  commits. It clones a git repo at the configured tag.

- The `gitlab-tag-git` and `github-tag-git` profiles use the
  `GitLabTagProvider` or `GitHubTagProvider` to resolve versions. The
  profiles git clone a project over `https` or `ssh` protocol.

- The `gitlab-tag-download` and `github-tag-download` are similar to
  `gitlab-tag-git` and `github-tag-git` profiles. Instead of cloning a git
  repository, they download a git tarball or an release artifact.

- The `hooks` profile calls the `resolver_provider` and `download_source`
  [hooks](../reference/hooks.rst).

- The `not-available` profile raises an error. It can be used to block a
  package and only enable it for a single variant.

### default behavior and hooks

When a package setting file does not have a top-level `source` configuration,
then Fromager keep its old behavior. It first looks for `resolver_provider`
and `download_source` [hooks](../reference/hooks.rst), then looks for source
distributions on PyPI.

When a package has a plugin with a `resolver_provider` or `download_source`
hook and `source` settings, then at least one `source` setting (top-level or
variant) must use `provider: hooks`. The rule ensures that the hooks are
used.

### git clone

Like pip's VCS feature, all git clone operations automatically retrieve all
submodules recursively. The final sdist does not include a `.git` directory.
Instead Fromager generates a `.git_archival.txt` file for setuptools-scm's
[builtin mechanism for obtaining version numbers](https://setuptools-scm.readthedocs.io/en/latest/usage/#builtin-mechanisms-for-obtaining-version-numbers).

The resolver and `Candidate` class do not support VCS URLs, yet. Fromager can
adopt pip's [VCS support](https://pip.pypa.io/en/stable/topics/vcs-support/)
syntax. The URL `git+https://git.example/viking/viking.git@v1.1.0` clones the
git repository over HTTPS and checks out the tag `v1.1.0`.

### Matcher factory

The matcher factory argument is an import string. The string must resolve to
a callable that accepts a `ctx` argument and returns a `re.Pattern`
(recommended) or `MatchFunction`. If the return value is a pattern object,
then it must have exactly one match group. The pattern is matched with
`re.match`.

The default matcher factory parsed the tag with `packaging.version.Version`
and ignores any error. Fromager will provide additional matcher factories for
common tag patterns like `v1.2`, `1.2`, and `v1.2-stable`.

```python
import re

from fromager import context, resolver
from packaging.version import Version


def matcher_factory_pat(ctx: context.WorkContext) -> re.Pattern | resolver.MatchFunction:
    # tag must match 'v1.2+midstream.1.cpu' and results in Version("1.2+midstream.1")
    variant = re.escape(ctx.variant)
    pat = rf"^v(.*\+midstream\.\d+)\.{variant}$"
    return re.compile(pat)


def matcher_factory_func(ctx: context.WorkContext) -> re.Pattern | resolver.MatchFunction:
    def pep440_matcher(identifier: str, item: str) -> Version | None:
        try:
            return Version(item)
        except ValueError:
            return None
    return pep440_matcher
```

### Deprecations

- `download_source.url` is handled by `pypi-download` profile or
  `release_artifact` parameter of `github` or `gitlab` provider
- `download_source.destination_filename` is not needed. All sdists use
  standard `{dist_name}-{version}.tar.gz` file name
- `resolver_dist.sdist_server_url` is replaced by `index_url` parameter.
  All `pypi-*` profile support a custom index.
- `git_options.submodules` is not needed. Like pip, Fromager will always
  clone all submodules.
- variant settings `wheel_server_url` and `pre_build` are replaced by
  `pypi-prebuilt` profile

### Migration

Top-level and variant-specific `source` settings are mutually exclusive with
`download_source`, `resolver_dist`, `wheel_server_url`, and `pre_build`
settings. It is an error to combine the new `source` settings with any of the
old settings.
