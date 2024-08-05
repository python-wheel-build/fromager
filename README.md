# fromager

Fromager is a tool for completely re-building a dependency tree of
Python wheels from source.

The goals are to support guaranteeing

1. The [binary
   package](https://packaging.python.org/en/latest/glossary/#term-Built-Distribution)
   someone is installing was built from source in a known build
   environment compatible with their own environment
1. All of the package’s dependencies were also built from source -- any
   binary package installed will have been built from source
1. All of the build tools used to build these binary packages will
   also have been built from source
1. The build can be customized for the packager's needs, including
   patching out bugs, passing different compilation options to support
   build "variants", etc.

The basic design tenet is to automate everything with a default
behavior that works for most PEP-517 compatible packages, but support
overriding all of the actions for special cases, without encoding
those special cases directly into fromager.

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
