# Multiple cache wheel servers

- Author: Christian Heimes
- Created: 2026-04-16
- Status: Open

## What

Support multiple cache wheel server URLs instead of a single
`--cache-wheel-server-url`. Caches are checked in order, similar to pip's
`--extra-index-url` or uv's `unsafe-best-match` index strategy.

## Why

In downstream, each variant and CPU architecture has its own build cache in
a GitLab PyPI registry. During bootstrap and build, fromager uses a
read/write cache in GitLab to avoid rebuilding wheels that were already built
for the current architecture. After a successful bootstrap and build, wheels
for all architectures are copied into a variant-specific cache in Pulp.

Currently fromager only supports a single `--cache-wheel-server-url`. To
pull from both the arch-specific GitLab cache **and** the variant-wide Pulp
cache, we need ordered multi-cache support.

All cache indexes are fully trusted and controlled by us, so security
concerns around index mixing (as with pip's `--extra-index-url`) do not
apply.

## Goals

- Accept multiple cache wheel server URLs on the CLI and in
  `WorkContext`.
- Check caches in order: local wheel server first, then each cache URL in
  the order specified.
- Remain backwards-compatible: a single `--cache-wheel-server-url` keeps
  working.
- Integrate with `build_environment.py` so build-dependency installation
  also searches multiple caches.

## Current state

`bootstrap`, `build-sequence`, and `build-parallel` each accept a single
`-c` / `--cache-wheel-server-url` option. The cache URL is not stored on
`WorkContext`; it is threaded through function arguments.

`wheels.get_wheel_server_urls()` builds an ordered list for resolution:

1. Per-package variant `wheel_server_url` (if set, used exclusively)
2. `ctx.wheel_server_url` (local wheel server)
3. `cache_wheel_server_url` (single cache, appended last)

Build-dependency installation (`build_environment.BuildEnvironment`) only
uses the local wheel server (`--index-url`). The cache is not passed to
pip/uv when installing build dependencies.

`Bootstrapper._download_wheel_from_cache()` checks the single cache URL
and downloads the first matching wheel.

## Proposed changes

### 1. CLI: accept multiple `--cache-wheel-server-url` values

Make the existing `-c` / `--cache-wheel-server-url` click option
repeatable (`multiple=True`). The internal parameter name changes from
`cache_wheel_server_url` (singular) to `cache_wheel_server_urls`
(sequence). A single `-c URL` keeps working.

### 2. Make `cache_wheel_server_urls` arguments a sequence

All internal call sites that currently pass a single
`cache_wheel_server_url: str | None` change to accept a sequence.
`wheels.get_wheel_server_urls()` appends all cache URLs in order instead
of a single one.

Affected modules: `commands/bootstrap.py`, `commands/build.py`,
`bootstrapper.py`, `bootstrap_requirement_resolver.py`, `wheels.py`.

### 3. Bootstrapper: iterate over caches

`Bootstrapper._download_wheel_from_cache()` iterates over all cache URLs
instead of checking a single one. The first cache that has a matching
wheel wins (first-match semantics, same as `--extra-index-url`).

### 4. Build environment: pass caches to pip/uv

Store `cache_wheel_server_urls` on `WorkContext` and extend
`pip_wheel_server_args` to emit `--extra-index-url` for each cache URL.
`BuildEnvironment.install()` then picks up caches automatically.

Set `UV_INDEX_STRATEGY=unsafe-best-match` in the build environment so uv
considers all indexes equally and picks the best matching version across
all of them, rather than stopping at the first index that has any version
of a package.

`WorkContext` already carries the local wheel server URL, so the cache
URLs belong there too -- they share the same lifetime.

### 5. Resolution order

The final resolution order for wheel lookups:

1. **Per-package variant `wheel_server_url`** -- if set, used exclusively
   (no change).
2. **Local wheel server** (`ctx.wheel_server_url`) -- just-built wheels.
3. **Cache 1** (first `-c` URL) -- e.g., variant-wide Pulp cache
   (read-only).
4. **Cache 2** (second `-c` URL) -- e.g., arch-specific GitLab PyPI
   registry (read/write).
5. ... additional caches in CLI order.

This matches the use case: check local builds first, then the Pulp cache
with already-published wheels, then the arch-specific GitLab cache.

## Example usage

```bash
fromager \
    --variant cuda \
    bootstrap \
    -c https://pulp.example/content/rhel-ai-cuda/simple \
    -c https://gitlab.example/api/v4/projects/123/packages/pypi/simple \
    -r requirements.txt
```

## Migration

- The CLI flag name stays the same (`--cache-wheel-server-url` / `-c`).
- Existing invocations with zero or one `-c` flag work without changes.
- The singular parameter name `cache_wheel_server_url` is renamed to
  `cache_wheel_server_urls` in internal APIs. This is a breaking change
  for any downstream code calling these functions directly.
