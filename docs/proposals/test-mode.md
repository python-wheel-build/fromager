# Bootstrap `--test-mode`: resilient source builds with pre-built fallback

- Author: Lalatendu Mohanty, Doug Hellmann
- Created: 2026-06-01 (retrospective; feature merged 2025-12-19)
- Status: Implemented
- GitHub issue: [#713](https://github.com/python-wheel-build/fromager/issues/713)
- Pull request: [#865](https://github.com/python-wheel-build/fromager/pull/865)

## What

Serial `fromager bootstrap --test-mode` continues after failures instead of
aborting. On source-build failure, fromager downloads a pre-built wheel for
the same package so traversal can proceed; dependents are still discovered and
built. The run ends with `test-mode-failures-<timestamp>.json` and exit code 1
if any failure was recorded.

Primary outputs of a degraded run are `graph.json`, `build-order.json`, and the
failure report—not a full set of source-built wheels.

## Why

Large source bootstraps often fail one package at a time. Without fallback,
dependents fail too, hiding which packages have real build problems. Operators
work around this by manually marking failures as `pre_built` and re-running
bootstrap repeatedly ([#713](https://github.com/python-wheel-build/fromager/issues/713)).

Test mode automates that loop: continue traversal, substitute pre-built wheels
on source failure, surface many build gaps in one run, and emit a structured
failure list for automation.

## Goals

- Continue serial `bootstrap` after failures; fallback via
  `BootstrapRequirementResolver.resolve(..., pre_built=True)`.
- Classify failures: `resolution`, `bootstrap` (fatal, error log) vs `hook`,
  `dependency_extraction` (non-fatal, warning log). All are recorded; any
  failure yields exit code 1.
- Preserve graph traversal and record `source_url_type` in `build-order.json`
  (`"prebuilt"` marks fallback wheels).

## Non-goals

- `bootstrap-parallel` (serial only); incompatible with `--sdist-only`.
- Replacing fail-fast default bootstrap or treating fallback wheels as the
  shipped product.
- Recording source-build failures when fallback succeeds ([#1166](https://github.com/python-wheel-build/fromager/issues/1166)).

## How

`commands/bootstrap.py` enables the flag; logic lives in `Bootstrapper`
([iterative-bootstrap.rst](iterative-bootstrap.rst)).

### Architecture

**Run flow** — serial `bootstrap` with `--test-mode` never aborts the whole
command on a single package failure; it finishes the run and reports at the end.

Resolve top-level requirements → Bootstrap dependency tree → finalize →
graph.json + build-order.json + failures JSON

**On error** — `_handle_phase_error()` in `bootstrapper.py` decides whether to
skip the package, substitute a pre-built wheel, or continue with a warning.

On phase error, branch by context:

- **Resolution** → Record failure, skip package
- **Source build** → Is a pre-built wheel available?
  - Yes → Use wheel, continue traversal
  - No → Record failure, skip package
- **Hook or dep extraction** → Record warning, continue

**Phase errors** (`_handle_phase_error()`):

| Context | Behavior |
| -- | -- |
| `RESOLVE` | Record `resolution`; skip |
| `PREPARE_SOURCE` / `PREPARE_BUILD` / `BUILD` | `_handle_test_mode_failure()`: resolve+download pre-built wheel; on success advance to `PROCESS_INSTALL_DEPS` with `SourceType.PREBUILT`; else record `bootstrap` |
| Post-bootstrap hooks | Record `hook` (warning); continue |
| Install dep extraction | Record `dependency_extraction` (warning); empty deps |

Settings `pre_built` packages skip the fallback path. Failure records include
package, version, exception type/message, and `failure_type`; see
`FailureRecord` in `bootstrapper.py`.

**Artifacts:** `build-order.json` `source_url_type` reflects runtime fallback;
graph node `pre_built` reflects settings only (not updated after fallback).

|  | `--test-mode` | `--multiple-versions` |
| -- | -- | -- |
| Purpose | Source-build gap analysis | All matching versions |
| On build failure | Pre-built fallback, keep traversing | Remove version from graph |
| Output | `test-mode-failures-*.json` | Logs only |

## Usage

```bash
fromager bootstrap --test-mode -r requirements.txt
```

Review `test-mode-failures-*.json`, `build-order.json` (`source_url_type: "prebuilt"`), and `graph.json`. Tests: `tests/test_bootstrap_test_mode.py`,
`e2e/test_mode_*.sh`.

## Limitations

1. Source-build failure not recorded when fallback succeeds ([#1166](https://github.com/python-wheel-build/fromager/issues/1166)).
2. Audit fallback via `build-order.json`, not graph `pre_built`.
3. Serial bootstrap only.
4. Pre-built version may differ from requested source version (warning logged).

## Key source files

`commands/bootstrap.py`, `bootstrapper.py`, `bootstrap_requirement_resolver.py`,
`dependency_graph.py`
