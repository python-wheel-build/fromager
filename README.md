# fromager

Fromager is a tool for rebuilding complete dependency trees of Python
wheels from source.

## Goals

Fromager is designed to guarantee that:

* Every binary package you install was built from source in a reproducible environment compatible with your own.

* All dependencies are also built from source, no prebuilt binaries.

* The build tools themselves are built from source, ensuring a fully transparent toolchain.

* Builds can be customized for your needs: applying patches, adjusting compiler options, or producing build variants.

## Design Principles

Fromager automates the build process with sensible defaults that work for most PEP-517–compatible packages. At the same time, every step can be overridden for special cases, without baking those exceptions into Fromager itself.

## Build Collections of Wheels

Fromager can also build wheels in collections, rather than individually. Managing dependencies as a unified group ensures that:

* Packages built against one another remain ABI-compatible.

* All versions are resolved consistently, so the resulting wheels can be installed together without conflicts.

This approach makes Fromager especially useful in Python-heavy domains like AI, where reproducibility and compatibility across complex dependency trees are essential.

## Using private registries

Fromager uses the [requests](https://requests.readthedocs.io) library and `pip`
at different points for talking to package registries. Both support
authenticating to remote servers in various ways. The simplest way to integrate
the authentication with fromager is to have a
[netrc](https://docs.python.org/3/library/netrc.html) file with a valid entry
for the host. The file will be read from `~/.netrc` by default. Another location
can be specified by setting the `NETRC` environment variable.

For example, to use a gitlab package registry, use a [personal
access
token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html#create-a-personal-access-token)
as documented in [this
issue](https://gitlab.com/gitlab-org/gitlab/-/issues/350582):

```plaintext
machine gitlab.com login oauth2 password $token
```

## Determining versions via GitHub tags

In some cases, the builder might have to use tags on GitHub to determine the version of a project instead of looking at
pypi.org. To avoid rate limit or to access private GitHub repository, a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) can be passed to fromager by setting
the following environment variable:

```shell
GITHUB_TOKEN=<access_token>
```

## Additional docs

* [Using fromager](docs/using.md)
* [Package build customization instructions](docs/customization.md)
* [Developer instructions](docs/develop.md)

## What's with the name?

Python's name comes from Monty Python, the group of comedians. One of
their skits is about a cheese shop that has no cheese in stock. The
original Python Package Index (pypi.org) was called The Cheeseshop, in
part because it hosted metadata about packages but no actual
packages. The wheel file format was selected because cheese is
packaged in wheels. And
"[fromager](https://en.wiktionary.org/wiki/fromager)" is the French
word for someone who makes or sells cheese.
