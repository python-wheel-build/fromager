# `build-parallel` scheduling: keep workers busy, keep building past failures

- Author: Christian Heimes
- Created: 2026-11-17
- Status: Proposed

## What

Three changes to how `fromager build-parallel` schedules builds. All three
serve the same goal: finish large build graphs faster by keeping workers busy.

1. Builds start as soon as their *build dependencies* are ready. The command no
   longer waits for a whole group of builds to finish before it starts the next
   group.
2. A failure stops the run only when another package needs the failed one at build
   time. The run continues past a failed *runtime-only dependency* and reports all
   failures together at the end. This mode is opt-in: by default, the first failure
   stops the run, as it does today.
3. Heavy builds get a mode between "run alone" and "no exclusivity". At most one
   heavy build runs at a time. Small builds still run alongside it.

## Why

Today the command builds in groups, and one slow package in a group holds up
unrelated work that is ready to go.

A failure stops the run. That is the right call when other packages need the
failed package at build time, because those dependents can never succeed. Many
failures involve packages that nothing else needs at build time. Aborting the
whole run for those throws away unrelated, buildable work.

Fail-early stays the default for backwards compatibility. Operators who want
the rest of the graph built opt in.

The exclusivity setting is all or nothing. A package either runs completely
alone, or it runs next to anything. Some packages are heavy or flaky and must
not run next to each other. They do not need to block every other package in
the graph.

## New behavior

### Continuous scheduling

Today the scheduler works in batches. It collects every package whose *build
dependencies* are ready, starts the batch, and waits for the whole batch to
finish. Only then does it collect the next batch. One slow build keeps workers
idle even when other packages are ready to build.

Under the proposal, the batch behavior is removed and the scheduler queues a
package as soon as its *build dependencies* are ready. Each time a build finishes,
the scheduler queues whatever became ready. This applies to every run. Build order
and log output are no longer deterministic between runs. The proposal accepts that
loss for the gain in throughput.

### Failure handling

Every package in the graph has two roles. It can be a *build-time dependency*,
which Fromager installs into the build environment of another package. It can
also be a *runtime dependency*, which only appears in the `Requires-Dist` of
the shipped wheels. A package can hold both roles at once.

By default, the first failure stops the run. The opt-in mode changes only the
handling of a failure that nothing needs at build time.

When a package fails, the command checks if another package needs it at build
time. The direct build requirements of a package count, and so do the
`Requires-Dist` entries of a build requirement, because Fromager installs those
into the build environment too.

If the failed package is needed at build time, the run ends in a hard stop. Any
stop drains the same way: the command stops starting new work and cancels builds
that are still queued. It cannot cancel a build that is already running, so those
builds finish and the command waits for them. Failing *build dependencies* are
extremely rare, and they
usually fail early in the run, so the wasted work stays small. The hard stop is a
deliberate simplification. Stopping everything is easier to implement and reason
about than finding and skipping every dependent of the failed package.

In the opt-in mode, if the failed package is not a direct or indirect *build
dependency*, the run continues as a best-effort run. The command records the
failure and keeps building. At the end, it logs all recorded failures and writes
them to a machine-readable report, in the same place as the other reports it
already produces. The location also works when the dependency graph comes from a
URL or a read-only mount. The report says which package failed and why.

A caller tells the outcomes apart by exit code and by the presence of the
report file. A run that stops and a best-effort run use different exit codes.
Only a best-effort run with recorded failures writes the report. The design also
leaves room for more failure-handling modes later, for example a mode that
skips the dependents of a failed build requirement instead of stopping.

The build command cannot decide which artifacts are still installable. The build
graph does not reflect previously built packages, and the build cache or the
index may contain older builds that satisfy build requirements. Fromager also
never guaranteed that packages are built in install order. This has been an issue
with partial builds in the past. Subsequent promotion and filtering must check
for resolvable packages.

### Heavy builds share the pipeline

Think of the build pipeline as a multi-lane road. Ordinary builds are cars that
share all lanes. A fully exclusive build is a super heavy goods transport: it
needs the entire road, and nothing else builds while it runs. The new mode is a
truck in a single truck lane: one truck at a time, while the cars keep moving
in the other lanes. A package picks one of three modes: ordinary traffic, super
heavy goods transport, or the truck lane.

The limit counts builds, not packages. In a multi-version graph, two versions
of the same heavy package are two heavy builds. They wait for each other, like
two different heavy packages do. Scheduling and prioritization do not change.
Fully exclusive builds are still sorted last, and every exclusive build
eventually builds. The scheduler prevents starvation by adding only one
exclusive package, a truck or a super heavy goods transport, to the work queue
at a time.

### Relation to the bootstrap command

The parallel bootstrap command runs `build-parallel` for its build phase, so it
inherits these changes, including the opt-in failure mode.

## Non-goals

- The names of options and arguments, or other implementation details. The detailed
  design decides them.
- The sequential build command does not change.
- The default fail-early behavior of the build command does not change.
- The bootstrap command's continue-past-failures mode is not replaced.
- Failed builds are not retried.
- The number of builds that can run at once does not change.
- Deciding which built artifacts are still installable after a failure.
