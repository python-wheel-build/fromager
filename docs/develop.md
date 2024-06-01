# Developing these tools

## Unit tests and linter

The unit tests and linter rely on [tox](https://tox.wiki/) and a
recent version of Python 3 (at least 3.9).

Run `tox` with no arguments to run all of the tests. Use one of the
specific target environments for running fewer or different
tests. Refer to `tox.ini` for the list of possible targets.

## End-to-end tests

The `e2e` directory contains test scripts that run in pipelines in CI
to test behaviors of the entire system. Each script includes a comment
at the top explaining what the test is trying to demonstrate.
