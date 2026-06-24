# Filter environment variables

- Author: Christian Heimes
- Created: 2026-04-23
- Status: Open
- Issue: [#1083](https://github.com/python-wheel-build/fromager/issues/1083)

## What

A configurable filter for environment variables inherited by external
commands. Fromager strips sensitive variables from `os.environ` before
they reach build scripts, hooks, or other subprocesses.

## Why

Fromager runs arbitrary third-party code during builds -- PEP 517 hooks,
setup scripts, patching commands, git operations. Every subprocess
today inherits the full parent environment, including credentials,
CI tokens, and registry passwords that have no business inside a build.

This is a supply-chain risk. A compromised or careless build script can
read and exfiltrate any variable it inherits. The risk is higher in CI
environments where runners routinely carry cloud credentials, API tokens,
and service account keys.

Controlling which variables pass through also improves reproducibility.
Stray environment can silently alter build behavior (compiler flags,
proxy settings, locale overrides). Filtering makes builds more
deterministic.

`sudo` solves the same problem with `env_keep` and `env_delete` in
sudoers. This proposal follows that proven model.

References:

- [sudo env_keep / env_delete](https://www.sudo.ws/docs/man/sudoers.man/#Command_environment)

## Goals

- Filter sensitive environment variables from subprocesses
- No configuration means no filtering -- existing setups are unaffected

## How

### Configuration

A new `external_commands` section in `settings.yaml` with two optional
lists: `keep_env` (allowlist) and `delete_env` (blocklist). Both
default to empty.

```yaml
external_commands:
  keep_env:
    - "SOME_VARIABLE"
    - "OTHER_*"
  delete_env:
    - "CREDENTIALS"
    - "CI_TOKEN"
```

### Pattern matching

Entries without `*` are exact matches. Entries ending with `*` are
prefix matches: `AWS_*` matches `AWS_REGION`, `AWS_SECRET_ACCESS_KEY`,
etc. A `*` in any other position is a validation error. A bare `*` is
only valid in `delete_env` (catch-all); in `keep_env` it is a
validation error.

### Evaluation order

`keep_env` is evaluated before `delete_env`. All checks are case-insensitive
and short-circuit. If a variable matches the hard-coded always-keep set or
an entry in `keep_env`, then the variable is kept.

For each variable in `os.environ`:

1. If it is in a hard-coded always-keep set -- **keep**, regardless of
   configuration. The always-keep set contains variables required for
   basic subprocess operation and proxy settings: `HOME`, `HOSTNAME`,
   `LANG`, `LANGUAGE`, `LC_*`, `LOGNAME`, `NO_COLOR`, `PATH`, `SHELL`,
   `USER`, `http_proxy`, `https_proxy`, `no_proxy`.
2. If any `keep_env` entry matches -- **keep**.
3. If any `delete_env` entry matches -- **delete**.
4. Otherwise -- **keep** (default passthrough).

`delete_env: ['*']` can be used to prevent passthrough. It filters all
variables that neither match the always-keep set nor `keep_env` entries.

Variables injected by fromager itself (`extra_environ`,
`build_environment`, package-level `env`) are never filtered. They are
applied after the filter runs.

### API changes

`external_commands.run()` currently has no access to `WorkContext` or
settings. Making the filter configuration available there will require
API changes to the function signature or module state. The specifics of
that change are out of scope for this proposal and will be handled by a
separate proposal for the `external_commands` API.

### Examples

Strip everything except what builds need:

```yaml
external_commands:
  keep_env:
    - "CARGO_*"
  delete_env:
    - "*"
```

Remove a few known secrets, pass everything else:

```yaml
external_commands:
  delete_env:
    - "CI_TOKEN"
    - "REGISTRY_PASSWORD"
    - "AWS_*"
```
