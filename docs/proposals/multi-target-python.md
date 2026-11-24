# Build wheels for multiple target Python interpreters

- Author: Christian Heimes
- Created: 2026-11-20
- Status: Open
- Epic: [#1480](https://github.com/python-wheel-build/fromager/issues/1480)

## Problem

Fromager builds wheels for the interpreter that runs it. If you need wheels
for a second Python version, you run Fromager again in a second environment.
You then keep the two outputs apart and combine them yourself. This costs time
and is easy to get wrong. Fromager can pick the wrong wheel. It can check
Python version requirements against the wrong interpreter, or overwrite one
variant with another.

Python 3.14 makes this worse. `cp314` is the normal build, and `cp314t` is the
free-threaded build. A wheel for one does not work on the other, so a single
bootstrap run should produce both. Dependencies can depend on the target too.
Bootstrap checks a marker such as `foo; python_version < "3.14"` once, with the
interpreter that runs Fromager. With several targets, one answer is wrong for
at least one target.

Older Python versions are a second case. Fromager requires Python 3.12 or
newer, but some downstreams still need wheels for 3.10 and 3.11. Today the
only path is an old Fromager release in an old environment. A target is a
build environment, so the Fromager runtime version does not have to match it.
This case depends on the Python stack. uv, build, packaging, and the build
backends must still support the target version. When they drop a version, it
stops being a usable target.

## Intended outcome

Fromager accepts one primary target and zero or more additional targets. If
you set no target, behavior stays the same, and Fromager builds for its
runtime Python interpreter. A target can be older than the Fromager runtime.
You can build 3.10 or 3.11 wheels with Fromager on 3.12 or newer.

Fromager builds the primary target first. It builds an additional target only
if the primary wheel cannot serve it. It builds a pure Python wheel once, and
a GIL stable-ABI wheel such as `cp312-abi3` covers Python 3.12 and newer but
not free-threaded builds. Fromager judges compatibility from wheel tags.
Python 3.15 ships multi-ABI wheels such as `cp315-abi3.abi3t`. One such wheel
serves both the GIL target and the free-threaded target, so neither needs a
second build.

One run produces all requested wheels, and they are distinguishable. One
variant does not overwrite another, and you do not move files between
directories by hand.

Resolution runs once per target. Environment markers, prebuilt wheel reuse,
and `Requires-Python` checks all use that target, not the interpreter that runs
Fromager. A requirement such as `foo; python_version < "3.14"` applies to the
targets it matches. Requirements can also demand different versions for
different targets, for example `foo<2; python_version < "3.14"` and
`foo>=2; python_version >= "3.14"`. When they do, each target builds the
version its marker selects. The extra resolution passes reuse cached index
data, so they stay cheap.

Reports, the SBOM, and logs record the target for each wheel. If Fromager
cannot produce a requested variant, it reports that and names the target and
the distribution.

Each target is either required or optional. Fromager fails the run when a
required target cannot build a distribution. A `Requires-Python` exclusion is
not a failure, so Fromager skips that distribution for the target. An optional
target skips a distribution that fails to build, and it reports each skip. A
skip also applies to packages that need the skipped distribution for that
target, and the report lists them. Optional targets let a downstream adopt a
newer Python in steps: mark the new target optional while packages catch up,
then make it required.

## Scope

- Target interpreters that the user supplies or that are already installed.
- Targets older than the Fromager runtime, such as 3.10 and 3.11.
- One Fromager run for a primary target and any number of additional targets.
- Required and optional targets, so a downstream can adopt a newer Python
  version gradually.
- Resolution, dependency markers, build environments, wheel output, reports,
  the SBOM, and logs.

## Non-goals

- Cross-compile for another OS, architecture, or libc.
- Download or manage Python interpreters. The user provides the targets or
  already has them installed. uv-managed Python may be an option, but the
  details are out of scope.
- Run builds in parallel as an end in itself.

## Open questions

- How to declare targets, and what to call them. A CPython wheel ABI tag such
  as `cp312` or `cp314t` is a possible option, because it names the version
  and threading mode.
- Which target becomes the primary one: the first declared entry or the oldest
  Python version.
- Which naming and build tag scheme keeps variants unambiguous downstream.
- What happens when the primary variant of a distribution fails but an
  additional target could still build.
- Whether the primary target can be optional.
- How the primary-first rule applies. One option builds both variants of a
  distribution before the next one. Another finishes the primary bootstrap
  first.
- What exit code Fromager uses when optional targets skip distributions:
  success, or a distinct soft-failure code.
- How old a target can be, given the Python versions that uv, build,
  packaging, and the build backends still support.
- How Fromager recognizes that one multi-ABI wheel serves both the GIL and
  free-threaded targets, and how that changes the skip decision.
