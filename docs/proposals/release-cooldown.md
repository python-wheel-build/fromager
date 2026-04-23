# Release cooldown for version resolution

- Author: Lalatendu Mohanty
- Created: 2026-03-31
- Status: Open
- Issue: [#877](https://github.com/python-wheel-build/fromager/issues/877)

## What

A configurable minimum release age ("cooldown") for version resolution.
When enabled, fromager skips package versions published fewer than N
days ago. One global setting controls all providers. Per-package
overrides allow exceptions.

## Why

Supply-chain attacks often publish a malicious package version and rely
on automated builds picking it up immediately. A cooldown window lets
the community detect and report compromised releases before fromager
consumes them. It also means new versions get broader testing before
entering the build.

References:

- [We should all be using dependency cooldowns](https://blog.yossarian.net/2025/11/21/We-should-all-be-using-dependency-cooldowns)
- [Malicious sha1hulud](https://helixguard.ai/blog/malicious-sha1hulud-2025-11-24)

## Goals

- A single `--min-release-age` CLI option (days, default 0) that
  applies to every resolver provider
- Per-package overrides via `resolver_dist.min_release_age` in package
  settings, taking priority over the CLI default
- Provider-aware fail-closed: providers that support timestamps
  reject candidates with missing `upload_time`; providers that do
  not support timestamps skip cooldown with a warning. A future
  strictness option may be added to control enforcement for
  providers that gain timestamp support (e.g., Phase 3), allowing
  gradual rollout without breaking existing builds.
- Pre-built wheels subject to cooldown when the index supports
  timestamps; bypass via per-package override otherwise
- `list-versions` shows timestamps, ages, and cooldown status
- `list-overrides` shows per-package cooldown values
- Age calculated from bootstrap start time, not wall-clock time during
  resolution

## Non-goals

- **Provider-specific flags** (`--pypi-min-age`, `--github-min-age`).
  The provider a package uses (PyPI, GitHub, GitLab) reflects *how* it
  is obtained, not how trusted it is. Most GitHub/GitLab packages are
  there because of broken PyPI sdists or midstream forks. Separate
  flags per provider would create a confusing configuration matrix and
  cannot coexist cleanly with a global model. This proposal uses one
  global default plus per-package overrides.
- **SSH transport** for git timestamp retrieval.

### Future consideration: `==` pin exemptions

Whether `==` pins in top-level requirements or constraints files
should automatically bypass cooldown is deferred. The per-package
`resolver_dist.min_release_age: 0` override already provides an
explicit, auditable escape hatch for packages that need to use
recently-published versions. Adding automatic `==` exemptions
would introduce a special case that weakens the security model
and requires users to understand the distinction. This can be
revisited if the per-package override proves too cumbersome in
practice.

## How

### Configuration

#### CLI and environment variable

A top-level `--min-release-age` option accepts a non-negative integer
(days, default 0). Negative values are rejected. The corresponding
environment variable `FROMAGER_MIN_RELEASE_AGE` is automatically
available via Click's `auto_envvar_prefix`.

The value is stored on `WorkContext` with a `start_time` captured once
at construction (UTC). A fixed start time ensures consistent results
when the same package is resolved multiple times during a build.

#### Per-package overrides

A new field in `ResolverDist`:

```yaml
# Trusted internal package -- bypass cooldown
resolver_dist:
  min_release_age: 0

# Extra scrutiny -- 2-week cooldown
resolver_dist:
  min_release_age: 14
```

Semantics:

- `None` (default) -- use the global `--min-release-age`
- `0` -- no cooldown for this package
- Positive integer -- override the global value

The effective cooldown for a package is resolved by checking the
per-package override first, falling back to the global default.

### Enforcement

During candidate validation, `BaseProvider` rejects candidates
whose age is less than the effective cooldown. The behavior
depends on whether the provider can supply timestamps:

- **Supports timestamps** (e.g. PyPI with PEP 691, GitLab):
  candidates with a known `upload_time` younger than the cutoff
  are rejected. A candidate with no `upload_time` is also rejected
  (fail-closed).
- **Does not support timestamps** (e.g. GitHub, generic
  providers): cooldown is skipped with a one-time warning per
  package. Custom providers inherit this default.

Each provider declares its timestamp capability. `PyPIProvider`
supports timestamps by default but allows callers to opt out for
indexes that only implement PEP 503 (no `upload-time` field).

After provider creation, the resolver supplies:

- The effective cooldown period (days, after resolving global vs.
  per-package override)
- The reference timestamp (bootstrap start time)

The provider uses these during candidate validation. Setting them
after construction ensures cooldown applies uniformly to all
providers -- including those returned by custom plugins -- without
requiring plugin changes.

#### Error messages

When cooldown blocks all candidates, error messages state the
reason clearly so users are not confused by a generic "no match":

- "found N candidate(s) for X but all were published within the last
  M days (cooldown policy)"
- "found N candidate(s) for X but none have upload timestamp metadata;
  cannot enforce the M-day cooldown"

### Timestamp availability

| Provider | `supports_upload_time` | Source |
| -- | -- | -- |
| PyPIProvider | Yes (PEP 691 indexes); No (PEP 503-only indexes) | `upload-time` field |
| GitLabTagProvider | Yes | `created_at` (tag or commit) |
| GitHubTagProvider | No | Needs Phase 3 |
| GenericProvider | No | Callback-dependent |
| VersionMapProvider | No | N/A |

Custom providers inherit `supports_upload_time = False` from
`BaseProvider`. Plugin authors that populate `upload_time` on
candidates should set the attribute to `True` in their provider's
constructor.

#### PyPI sdists (primary use case)

Most packages resolve through `PyPIProvider`, making PyPI sdists the
largest attack surface and the easiest to protect.

PyPI's PEP 691 JSON API provides `upload-time` per distribution
file, not per version. Each sdist and wheel has its own timestamp.
Fromager already reads this field via the `pypi_simple` library and
stores it on `Candidate.upload_time` -- no extra API calls needed.

When `sdist_server_url` points to a non-PyPI simple index (e.g., a
corporate mirror), `upload-time` may be absent. Fail-closed applies;
use `min_release_age: 0` for packages from indices without timestamps.

#### GitHub timestamps (Phase 3)

The GitHub tags list API does not return dates.
`GitHubTagProvider` sets `supports_upload_time = False`, so it
skips cooldown with a warning until Phase 3 adds timestamp
support via the Releases API and commit date fallback.

### Exempt sources

#### Pre-built wheels

Cooldown applies to pre-built wheels the same way it applies to
sdists: if the index supports timestamps (e.g. PyPI.org with
PEP 691), candidates younger than the cutoff are rejected. If the
index does not support timestamps, fail-closed applies. Use
`resolver_dist.min_release_age: 0` to bypass cooldown for
packages resolved from indices without timestamp support.

Fromager's internal build and cache wheel servers are not used for
version resolution, so cooldown does not apply to them.

#### Direct git clone URLs

Requirements with explicit git URLs (`pkg @ git+https://...@tag`)
bypass all resolver providers entirely. No candidate is created
and validation never runs, so there is no insertion point for a
cooldown check.

These are also exempt by design:

- Only allowed for top-level requirements, not transitive dependencies
- The user explicitly specifies the URL and ref -- this is a
  deliberate pin, not automatic version selection
- Git timestamps (author date, committer date) are set by the
  client, not the server, so they cannot be trusted for cooldown
  enforcement the way PyPI's server-side `upload-time` can

### Command updates

**`list-versions`**:

- Shows `upload_time` and age (days) for each candidate
- Marks candidates blocked by cooldown
- `--ignore-per-package-overrides` shows what cooldown would hide

**`list-overrides`** (with `--details`):

- New column for per-package `min_release_age`

## Implementation phases

### Phase 1 -- Core (single PR)

- `--min-release-age` CLI option and `WorkContext` support
- Per-package `resolver_dist.min_release_age` override in package
  settings
- Cooldown check in provider candidate validation
- `supports_upload_time` attribute on providers
- Cooldown set on the provider after creation so custom plugins
  work without changes
- Pre-built wheel exemption
- Unit tests

PyPI sdists and GitLab-sourced packages work immediately after this
phase (timestamps already available). GitHub-sourced packages require
Phase 3.

### Phase 2 -- Commands (follow-up PR)

- `list-versions` enhancements
- `list-overrides` enhancements

### Phase 3 -- GitHub timestamps (after Phase 1 is merged)

- A new `GitHubReleaseProvider` using the Releases API
  (`created_at` / `published_at`) with commit date fallback.
  GitHub's GraphQL API may be used for efficient bulk queries.
- GraphQL requires authenticated requests (bearer token). If no
  token is available and cooldown is active, fail-closed applies.

**Migration note**: Until Phase 3 ships, GitHub-sourced packages
skip cooldown with a warning (since `GitHubTagProvider` has
`supports_upload_time = False`). No manual `min_release_age: 0`
overrides are needed. Phase 3 enables cooldown enforcement for
these packages by adding timestamp support.

## Examples

```bash
# 7-day cooldown
fromager --min-release-age 7 bootstrap -r requirements.txt

# Same, via environment variable
FROMAGER_MIN_RELEASE_AGE=7 fromager bootstrap -r requirements.txt

# No cooldown (default)
fromager bootstrap -r requirements.txt

# Inspect available versions under a 7-day cooldown
fromager --min-release-age 7 package list-versions torch
```

```yaml
# overrides/settings/internal-package.yaml
resolver_dist:
  min_release_age: 0    # trusted, no cooldown

# overrides/settings/risky-dep.yaml
resolver_dist:
  min_release_age: 14   # 2-week cooldown
```
