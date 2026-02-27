# New resolver and download configuration

- Author: Christian Heimes

## What

This enhancement document proposal a new approach to configure the package
resolver and source / sdist downloader. The new settings are covering a
wider range of use cases. Common patterns like building a package from a
git checkout will no longer need custom Python plugins.

## Why

In downstream, we are encountering an increasing amount of packages that do
not build from sdists on PyPI. Either package maintainers are not uploading
source distributions to PyPI or sdists have issues. In some cases, packages
use a midstream fork that is not on PyPI. The sources need to be build from
git.

Because Fromager <= 0.76 does not have declarative settings for Github/Gitlab
resolver or cloning git repos, we have to write custom Python plugins. The
plugins are a maintenance burden.

## Goals

- support common use cases with package settings instead of custom plugin code
- cover most common resolver scenarios:
  - resolve package on PyPI (sdist, wheel, or both)
  - resolve package on Github or Gitlab with custom tag matcher
- cover common sdist download and build scenarios:
  - sdist from PyPI
  - prebuilt wheel from PyPI
  - download tarball from URL
  - clone git repository
  - build sdist with PEP 517 hook or plain tarball
- support per-variant setting, e.g. one variant uses prebuilt wheel while the
  rest uses sdist.
- gradual migration path from old system to new configuration

## Non-goals

- The new system will not cover all use cases. Some specific use cases will
  still require custom code.
- Retrival of additional sources is out of scope, e.g. a package `egg` that
  needs `libegg-{version}.tar.gz`.

## How

The new system will use a new top-level configuration key `source`. The old
`download_source` and `resolver_dist` settings will stay supported for a
while. Eventually the old options will be deprecated and removed.

The resolver and source downloader can be configuration for all variants of
a package as well as re-defined for each variant. Each use case is handled
a provider profile. The profile name acts as a discriminator field.

Example:

```yaml
source:
  # `pypi-sdist` is the default provider
  provider: pypi-sdist
variants:
  egg:
    source:
      # resolve and download prebuilt wheel
      provider: pypi-prebuilt
      index_url: https://custom-index.test/simple
  spam:
    source:
        # resolve on Gitlab, clone, build an sdist with PEP 517 hook
        provider: gitlab
        url: https://gitlab.test/spam/spam
        matcher_factory: package_plugins.matchers:midstream_matcher_factory
        retrieve_method: git+https
        build_sdist: pep517
  viking:
    source:
        # resolve on PyPI, git clone, and build as tarball
        provider: pypi-git
        clone_url: https://github.test/viking/viking.git
        tag: 'v{version}'
        build_sdist: tarball
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

- The `gitlab` and `github` profiles use the `GitlabTagProvider` or
  `GitHubTagProvider` to resolve versions. The profiles can either download
  a git tag tarball or clone the repo at a specific tag.

Like pip's VCS feature, all git clone operations automatically retrieve all
submodules recursively.


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
