# Explicit wheel build numbers

- Author: Mike DePaulo
- Created: 2026-10-23
- Status: Open
- GitHub issue: [#1390](https://github.com/python-wheel-build/fromager/issues/1390)

## What

Add an optional per-package `build_number` setting that supplies the numeric
part of a wheel build tag for a public version. When configured, it replaces
the number derived from changelog lengths. The existing `build_tag_hook`
continues to supply suffix segments. Whether the setting also constrains
dependency installation is an open scope decision below.

## Why

Build orchestration systems may already maintain rebuild counters separately
from Fromager's changelogs. Using those counters currently requires creating
synthetic changelog entries or changing imported changelogs to make their
combined length equal the desired number.

An explicit setting lets callers control the wheel's build number while
retaining changelogs as history. This complements the
[wheel build tag hook](wheel-build-tag-hook.md), which customizes the suffix
and does not replace the numeric portion.

## Goals

- Allow a caller to supply a nonnegative integer, including zero.
- Use the same expected tag when producing a wheel and checking for a reusable
  cached wheel.
- Preserve changelog defaults and suffix hooks for unconfigured versions.

## Non-goals

- Changing package-version resolution.
- Defining how callers increment counters or publish and retain wheel builds.
- Retagging pre-built wheels.

## How

### Configuration

In a package settings file:

```yaml
build_number:
  "1.2.3": 0
  "2.0": 7
```

Keys are public versions, without a local version suffix. Reject keys such as
`"1.2.3+custom"`; a request for that version uses the `"1.2.3"` entry.
Values must be nonnegative integers, excluding booleans and strings.

For a configured version, use the explicit number instead of the combined
variant and package changelog lengths. Do not add the two counts together.
Keep the changelog entries available as history. Versions without an entry
retain their existing changelog-derived behavior.

The proposed mapping applies to all variants for that package. A configured
number therefore overrides the numeric contribution of the variant changelog
as well. Variant-specific explicit numbers are a discussion point below.
Pre-built wheels retain their original tags; this setting does not affect them.

### Wheel identity and cache reuse

An explicit zero produces a numeric build tag of `0`; it does not mean an
omitted build tag. With no hook suffix, version `1.2.3` in the example produces
`example-1.2.3-0-py3-none-any.whl`, with `Build: 0` in its `WHEEL` metadata.

Apply the existing suffix hook after selecting the number. An explicit number,
including zero, supplies the base tag even when both changelogs are empty, so
the hook still runs. For example, `7` and hook segment `el9.6` produce `7_el9.6`.
The hook's signature remains unchanged. Installation-time inputs depend on the
scope option below.

Where Fromager checks whether a requested wheel has already been built,
require the complete expected build tag for explicitly configured versions.
Apply this consistently to local and remote cache candidates across bootstrap
and build workflows, alongside existing version and compatibility checks.
An untagged wheel does not satisfy explicit zero. A different tag, including
a higher numeric part or different suffix, is a cache miss. If no matching
wheel is available, build the requested wheel.

Unconfigured versions retain their existing cache behavior. Broader changes
to legacy cache semantics, discussed in
[#1360](https://github.com/python-wheel-build/fromager/issues/1360), are separate.

### Dependency installation: scope options

When compiling A, a requirement such as `B==1.0` does not specify B's wheel
build tag. Even if Fromager produces or retrieves B's configured build `1`,
the installer may select another build of B from the available candidates.
There are three options for the scope of this feature.

#### Option 1: exact dependency builds from local wheels

Require dependencies with explicit numbers to match their complete expected
build tags, including transitive dependencies. Filter the locally available
wheels, reinstall dependencies in reused environments, and check installed
`WHEEL` metadata before compilation. Fail if a required matching artifact is
unavailable or a direct reference installs a different build.

This is the working proof of concept in
[#1391](https://github.com/python-wheel-build/fromager/pull/1391). Any loaded
non-prebuilt package with a configured number activates local-only installation
for the invocation, even if that package/version is unused. All dependency
wheels must be available locally, including unconfigured and pre-built wheels;
installation does not fetch from `--wheel-server-url`.

This offers exact-build enforcement without implementing remote artifact
selection, but changes existing remote-source workflows. Logging makes the
restriction visible; it does not remove it. The filtered view must stay current
without repeatedly recreating every link or letting concurrent installs alter
one another's candidate sets. The prototype reuses a view per worker and updates
changed links, while still scanning filenames before each install.

#### Option 2: wheel generation and cache reuse only

`build_number` controls the wheel Fromager produces or reuses, without locking
the wheel installed as a dependency of another package. Preserve existing
dependency installation and configured wheel sources.

This keeps the change small and avoids coupling a package's numeric setting
to installation policy across the invocation. It does not guarantee that
compilation uses each dependency's configured build. Exact dependency-artifact
selection could be designed separately if this option is chosen.

#### Option 3: exact dependency builds through configured sources

Enforce complete expected build tags for dependencies with explicit numbers,
including transitive dependencies, while preserving configured remote sources.
Keep existing selection behavior for unconfigured versions and pre-built wheels.
Fail before compilation if a required matching artifact is unavailable.

This gives callers a stronger guarantee about build inputs without requiring
all wheels locally. It also requires more design: selecting compatible artifacts
from authenticated sources, constraining transitive dependencies, replacing
other builds in reused environments, and handling installer caches. Exact wheel
URLs or a filtered index could express the selection; a version constraint alone
cannot. The implementation approach remains open.

Option 1 remains implemented as a proof of concept while the scope is
discussed; that does not settle the upstream design. The choice among all
three options remains open for upstream discussion. Should exact dependency-build enforcement be included now,
and if so, is a local-only workflow acceptable or is option 3 required?

## Alternatives

- **Synthetic changelogs:** reuse existing behavior, but make historical entries
  serve as a numeric configuration mechanism and complicate imported settings.
- **Extend the suffix hook to choose the number:** permits arbitrary logic but
  changes the hook contract and requires executable code for a static value.

## Discussion

**Variant scope:** Should this first version support variant-specific overrides?
The proposed package-level mapping is simple, but changelog-derived numbers can
already differ between variants. A compatible extension could keep this mapping
as the default and add variant overrides through the existing settings structure.

**Activation:** If dependency enforcement is included, should any loaded counter
activate it, only counters for dependencies selected in this invocation, or a
separate opt-in setting? The prototype uses the first rule. Narrower activation
needs a defined point for determining the relevant dependency set, including
transitive dependencies. Option 2 avoids this installation-policy decision.

**Hook inputs:** The prototype reconstructs bare requirements from wheel and
installed-distribution names during installation checks. Hooks must therefore
produce the same suffix using only the name, version, variant, and `wheel_tags`,
within the existing hook restrictions on compatibility tags. Extras, markers,
specifiers, and URLs are unavailable there. Is that narrower contract acceptable
for enforcement, or should the original requirement context be retained? Option
2 avoids adding these installation-time hook calls.

## Validation

Test explicit zero and nonzero values, invalid keys and values, changelog
fallback, variants, suffix hooks, and local and remote cache matches. Verify
generated filenames and `WHEEL` metadata with a source build.

For option 2, verify that configuring a counter preserves existing dependency
installation and remote sources. For either enforcement option, test direct and
transitive dependencies, competing builds, reused environments, installer caches,
direct references, missing artifacts, and hook-input consistency. Verify the
chosen activation rule, including unused counters and pre-built packages.

Option 1 should fail when required wheels are absent locally even if a remote
index serves them. Check view freshness, link reuse, and parallel isolation.
Option 3 additionally needs authenticated remote-source and artifact-selection
tests. Any filtering approach needs performance evaluation on large wheel sets.
