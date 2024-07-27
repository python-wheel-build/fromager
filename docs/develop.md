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

## Logging

Log messages should be all lower case.

When possible, log messages should be prefixed with the name of the distribution
being processed.

Information about long running processes should be logged using the "unit of
work" pattern. Each long step should be preceded and followed by log messages
writing to INFO level to show what is starting and stopping, respectively.

Detailed messages should be logged to DEBUG level so they will not appear on the
console by default.
