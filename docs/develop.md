# Developing these tools

## Local development/testing

The tools should work as-is on a Fedora system. Use `setup.sh` to
install some system dependencies for running the tool scripts and for
compiling some of the target packages.

Podman is also required in some cases, and is not installed by
`setup.sh`.

Use the `cli` tox environment to run the tool without having to manage
your own virtualenv for variations of commands not supported directly
by the script wrappers. For example

```
$ tox -e cli -- --no-cleanup bootstrap numpy
```

is basically the same as `mirror-sdists.sh numpy` but leaves the
source trees for all of the packages on the filesystem to be examined,
something that is too expensive to do normally in container builds. It
also allows you to reuse any of the build artifacts between
iterations, so you don't have to wait for expensive dependencies to
compile again.

### Unit tests and linter

The unit tests and linter rely on [tox](https://tox.wiki/) and a
recent version of Python 3 (at least 3.9).

Run `tox` with no arguments to run all of the tests. Use one of the
specific target environments for running fewer or different
tests. Refer to `tox.ini` for the list of possible targets.

### End-to-end tests

The `e2e` directory contains test scripts that run in pipelines in CI
to test behaviors of the entire system. Each script includes a comment
at the top explaining what the test is trying to demonstrate.
