# `build-parallel` scheduling: continuous queue, `--on-error`, concurrent-exclusive builds

- Author: Christian Heimes
- Created: 2026-11-09
- Status: Proposed

## What

Three independent improvements to how `fromager build-parallel` schedules builds:

1. **Continuous queue.** Build packages as soon as they're ready, instead of waiting
   for a whole group of packages to finish before starting the next group.
2. **`--on-error {abort,continue}`.** Optionally keep building after a failure of a
   non-build dependency, instead of always stopping the whole run. Failures are
   reported together at the end, including a structured JSON report for tooling.
3. **A middle ground for exclusive builds.** Today a package can only be "build this
   completely alone" or not exclusive at all. Add a third option: "build at most one
   of these at a time," which still lets ordinary packages build alongside it.

## Why

The overall goal is to increase throughput and reduce total pipeline time for large
dependency graphs.

Today, `build-parallel` builds in groups: it starts every package that's currently
buildable, then waits for the entire group to finish before checking what else became
buildable. One slow package in a group holds up the start of unrelated, independent
work that's ready to go.

A failure stops new rounds, but submitted builds finish before the command exits.
That's the right call when the failed package is a build dependency of another
package: those dependents could never be built regardless. But plenty of failures
involve packages that aren't a build dependency of anything else, and aborting the
entire run for those throws away unrelated, otherwise buildable work.

Finally, today's "exclusive build" setting is all-or-nothing: a package either runs
completely alone, or runs with no isolation at all. Some packages are heavy or flaky
enough to want to avoid running alongside *each other*, without needing to block every
other package in the graph.

## Goals

- Keep workers busy: start a package the moment it's buildable, not when its whole
  batch is buildable.
- Let a build continue past a failure of a package that isn't a build dependency of
  anything else, and finish everything unaffected by it, with all failures reported
  together at the end.
- Keep aborting immediately whenever the failed package is a build dependency of
  something else in the graph. Never attempt a build that's already known to be
  impossible.
- Allow a package to require "only one of me at a time" without demanding full
  isolation from the rest of the build.
- Leave room to add more failure-handling behavior later without another breaking
  change to the command-line interface.
- Give automation a machine-readable record of what failed and why, instead of only a
  human-readable log.
- Keep the current error-handling and exclusivity defaults. Continuous scheduling
  applies to all runs.

## Non-goals

- Changing the non-parallel, sequential build command.
- Changing or replacing the existing serial-bootstrap "continue past failures" mode.
  It's a separate feature (see [test-mode.md](test-mode.md)) that this proposal
  doesn't touch, beyond keeping the two commands' options consistent.
- Automatically retrying failed builds.
- Changing how many builds can run at once (worker/concurrency limits are unaffected).

## How

**Continuous queue**: the scheduler already supports being asked "what's ready?"
repeatedly. Ask again as soon as anything finishes. Track submitted nodes and
do not submit them again while their builds are queued or running.

**`--on-error continue`**: when a package fails, the command checks whether it's a
build dependency of another package in the graph. If so, it aborts immediately
(identical to today's behavior, since those dependents could never succeed anyway). If
it isn't a build dependency of anything else, the failure is recorded instead, and the
rest of the (unrelated) build keeps going normally.

Once nothing more can be built, if any failures were recorded, the command logs them
and exits with an error. It also writes them to a structured JSON report with a fixed
name next to the dependency graph file, similar in spirit to the failure report
already produced by serial bootstrap's `--test-mode` (see
[test-mode.md](test-mode.md)), though that one uses a timestamped filename instead.
Aborting on a build-dependency failure and finishing with one or more independent
failures recorded are different outcomes, so they use different, specific non-zero
exit codes, letting a caller tell a hard abort apart from a best-effort run that
still recorded some (independent) failures.

"Build dependency" here includes more than direct build requirements: it also covers
the install-time dependencies of a build requirement, i.e. whatever ends up installed
in the build environment. A package that's purely an install-time dependency of the
final shipped artifacts, and isn't needed to build anything else, is independent and
doesn't abort the run if it fails. A package that's an install-time dependency of a
build requirement is still part of that build dependency chain, so it does abort,
since something else's build genuinely needs it.

**Exclusive build, middle ground**: the existing per-package "build this alone"
setting gains a second option meaning "build at most one of these at a time, but let
other, ordinary packages build alongside it." A package picks one of: no exclusivity,
full isolation, or this new shared-but-serialized mode.

## Usage

```bash
fromager build-parallel --on-error continue graph.json
# on failure, also writes build-parallel-failures.json next to graph.json
```

```yaml
# package settings
build_options:
  exclusive_build: concurrent
```
