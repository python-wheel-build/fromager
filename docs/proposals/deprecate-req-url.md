# Deprecate PEP 508 Direct References (`req.url`)

**Status:** Proposed
**Date:** 2026-07-02
**Author:** Shanmukh Pawan

## What

Deprecate and eventually remove support for PEP 508 direct reference URLs (the `package @ git+https://...` syntax) as top-level bootstrap inputs. Migrate users to the declarative `source` provider config introduced in the [new resolver and download configuration proposal](https://fromager.readthedocs.io/en/latest/proposals/new-resolver-config.html).

## Why

PEP 508 direct references (parsed into `Requirement.url` by the `packaging` library) let users specify a git URL inline in a requirement string. Fromager added this in [5f3fa68](https://github.com/python-wheel-build/fromager/commit/5f3fa68) (2025-02-22) to support two use cases: building packages whose PyPI sdists were broken or unavailable, and building from branch HEAD for nightly builds to catch integration issues before tagged releases.

This feature sits outside fromager's normal pipeline. Because the `Requirement` object carries the URL instead of a version specifier, every pipeline phase (resolution, download, prepare, build sdist) needs a separate `if req.url:` branch to bypass its normal logic. The codebase currently has **19 such branches across 6 files**. Each subsequent commit ([4a080bb](https://github.com/python-wheel-build/fromager/commit/4a080bb), [45008ce](https://github.com/python-wheel-build/fromager/commit/45008ce), [e50247d](https://github.com/python-wheel-build/fromager/commit/e50247d), [5687cf7](https://github.com/python-wheel-build/fromager/commit/5687cf7)) added special-case handling to accommodate `req.url` in a pipeline that wasn't designed for it.

The scope is inherently narrow:

- Only top-level requirements. Transitive dependencies cannot carry URLs (PyPI rejects them per PEP 440).
- Only git URLs. No other VCS or URL type is supported.
- Only command-line input. Not declarative, not version-controlled, not per-variant.
- Requires cloning just to discover the version. The normal pipeline resolves versions without fetching source.

The new `source` provider config covers every `req.url` use case declaratively, without special-casing:

| Use case | `req.url` approach | `source` config replacement |
| -- | -- | -- |
| Build from git tag | `pkg @ git+https://repo@v1.0` | `provider: pypi-git` with `clone_url` and `tag` |
| Build from GitHub tag | `pkg @ git+https://github.com/org/repo@v1.0` | `provider: github-tag-git` with `project_url` |
| Build from GitLab tag | `pkg @ git+https://gitlab.com/org/repo@v1.0` | `provider: gitlab-tag-git` with `project_url` |
| Build from specific commit | `pkg @ git+https://repo@abc123` | `provider: versionmap-git` with `versionmap` |
| Build from branch HEAD | `pkg @ git+https://repo@main` | No direct equivalent yet. Requires a new provider that clones first and discovers the version from package metadata. |

## Decision

Deprecate `req.url` support with a warning, then remove it after users have migrated to `source` provider configs.

The deprecation is reversible. If unforeseen use cases emerge, the warning can remain indefinitely without blocking users.

## How

Phase 1: When a top-level requirement has `req.url` set, emit a deprecation warning with guidance pointing to the equivalent `source` provider config. No behavior change.

Phase 2: Add a migration guide documenting the before/after for each use case (git tag, git commit, branch HEAD).

Phase 3: After downstream migration is confirmed, remove the `req.url` code paths: the 19 `if req.url:` branches, `_resolve_version_from_git_url()`, and related helper methods in `bootstrapper.py`.

`gitutils.py` is retained. It is used by git-clone source providers via `default_download_source()`.
