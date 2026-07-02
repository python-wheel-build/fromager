# Plan: Refactor Bootstrapper Phase Handlers into PhaseItem Class Hierarchy

## Context

`Bootstrapper` in `src/fromager/bootstrapper.py` has grown large (~2268 lines). The seven `_phase_*` methods that implement the bootstrap loop's processing logic are co-mingled with orchestration, state tracking, and utility methods. The goal is to move each phase handler into its own class (`PhaseItem` subclass) that lives on the stack, wrapping a `WorkItem` data container. This makes each phase self-contained and easier to understand, test, and extend.

## Design

### New: `PhaseItem` abstract base class

Each object pushed onto the bootstrap stack is a `PhaseItem`. It wraps a `WorkItem` (the accumulated per-package state) and implements the logic for one phase.

```python
class PhaseItem(abc.ABC):
    phase: typing.ClassVar[BootstrapPhase]   # which phase this item represents
    tracks_why: typing.ClassVar[bool] = True  # whether to push onto why stack

    def __init__(self, work_item: WorkItem) -> None:
        self.work_item = work_item
        self.bg_future: concurrent.futures.Future[typing.Any] | None = None

    @abc.abstractmethod
    def run(self, bt: Bootstrapper) -> list[PhaseItem]: ...

    def background_work(self, bt: Bootstrapper) -> typing.Callable[[], typing.Any] | None:
        """Return a zero-argument callable for background I/O, or None.
        Override in subclasses that need background prefetching.
        ``bt`` is provided so subclasses can capture Bootstrapper state
        (e.g. resolver, ctx) into the returned closure without storing
        a circular reference on the item itself."""
        return None

    def __str__(self) -> str:
        """Human-readable representation for logging.
        Default: ``"<PhaseClassName>(<req>)"``. Subclasses may override."""
        wi = self.work_item
        return f"{type(self).__name__}({wi.req})"

    def as_json(self) -> dict[str, typing.Any]:
        """Return a JSON-serialisable dict for stack-state recording.
        The base implementation covers all common ``WorkItem`` fields.
        Subclasses may override to add phase-specific entries."""
        wi = self.work_item
        return {
            "req": str(wi.req),
            "req_type": str(wi.req_type),
            "phase": str(self.phase),
            "resolved_version": str(wi.resolved_version) if wi.resolved_version is not None else None,
            "source_url": wi.source_url,
            "build_sdist_only": wi.build_sdist_only,
            "why": [
                {"req_type": str(rt), "req": str(r), "version": str(v)}
                for rt, r, v in wi.why_snapshot
            ],
            "parent": (
                {"req": str(wi.parent[0]), "version": str(wi.parent[1])}
                if wi.parent else None
            ),
            "build_system_deps": sorted(str(r) for r in wi.build_system_deps),
            "build_backend_deps": sorted(str(r) for r in wi.build_backend_deps),
            "build_sdist_deps": sorted(str(r) for r in wi.build_sdist_deps),
        }
```

### New: 7 concrete `PhaseItem` subclasses

| Class | phase | tracks_why | overrides background_work |
| -- | -- | -- | -- |
| `ResolveItem` | RESOLVE | False | Yes (calls `_bg_resolve`) |
| `StartItem` | START | False | No |
| `PrepareSourceItem` | PREPARE_SOURCE | True | Yes (calls `_bg_prepare_source` or `_bg_prepare_prebuilt`) |
| `PrepareBuildItem` | PREPARE_BUILD | True | No |
| `BuildItem` | BUILD | True | No |
| `ProcessInstallDepsItem` | PROCESS_INSTALL_DEPS | True | No |
| `CompleteItem` | COMPLETE | True | No |

Each `run(self, bt: Bootstrapper) -> list[PhaseItem]` method contains the body of the corresponding `_phase_*` method. References to the old `self` (Bootstrapper) become `bt`; references to `item.*` become `self.work_item.*`.

#### Phase advancement pattern

The current handlers advance an item to the next phase by mutating `item.phase` then returning `[item]`. With `PhaseItem` classes the class encodes the phase, so mutation is impossible. Instead, each `run()` that continues the same package constructs a **new** `PhaseItem` subclass wrapping the same `work_item`:

```python
# Old: mutation
item.phase = BootstrapPhase.PREPARE_BUILD
return [item] + dep_items

# New: construction
return [PrepareBuildItem(self.work_item)] + dep_items
```

The expected return types per class are:

| Class | Returns |
| -- | -- |
| `ResolveItem` | `list[StartItem]` (one per resolved version) |
| `StartItem` | `[]` (already seen) or `[PrepareSourceItem]` |
| `PrepareSourceItem` | `[ProcessInstallDepsItem]` (prebuilt) or `[PrepareBuildItem] + dep_items` (source) |
| `PrepareBuildItem` | `[BuildItem] + dep_items` |
| `BuildItem` | `[ProcessInstallDepsItem]` |
| `ProcessInstallDepsItem` | `[CompleteItem] + dep_items` |
| `CompleteItem` | `[]` |

Assertions such as `assert item.bg_future is not None` in the current `_phase_resolve` and `_phase_prepare_source` bodies become `assert self.bg_future is not None` and must be retained in the corresponding `run()` methods.

#### `background_work()` and module-level helpers

`_bg_resolve`, `_bg_prepare_source`, and `_bg_prepare_prebuilt` are already **module-level functions** (not `Bootstrapper` methods). Closures built inside `background_work(self, bt)` capture them directly from module scope — `bt` is provided only to access `Bootstrapper` attributes (e.g. `bt._resolver`, `bt.ctx`) needed to construct the closure, not to store a reference to `bt` on the item.

### Changes to `BootstrapPhase`

The `BootstrapPhase` enum is **retained** — it is still referenced by `PhaseItem.phase: ClassVar[BootstrapPhase]` and used for its string values in `as_json()`, log messages, and error output.

- **Remove** the `tracks_why` property — it becomes dead code once `tracks_why` moves to `PhaseItem` class variables.

### Changes to `WorkItem`

- **Remove** `phase: BootstrapPhase` field — phase is now encoded in the `PhaseItem` subclass type
- **Remove** `bg_future` field — moved to `PhaseItem` base class
- All other fields remain unchanged (they accumulate state across phases via `work_item`)

### Changes to `Bootstrapper`

| What | Change |
| -- | -- |
| `_phase_resolve`, `_phase_start`, `_phase_prepare_source`, `_phase_prepare_build`, `_phase_build`, `_phase_process_install_deps`, `_phase_complete` | **Delete** — logic moves into `PhaseItem` subclasses |
| `_get_background_work()` | **Delete** — replaced by `PhaseItem.background_work()` |
| `_dispatch_phase(item)` | Simplify to `return item.run(self)`; remove the `match/case` block and the `case _: raise ValueError(...)` fallthrough (unreachable once all subclasses are concrete) |
| `_push_items(stack, items)` | Accept `list[PhaseItem]`; retain the `if self._bg_pool is not None` guard; iterate `reversed(items)` (LIFO) to submit the highest-priority item first; call `item.background_work(self)` instead of `self._get_background_work(item)` and if not None, `item.bg_future = self._bg_pool.submit(bg_work)` |
| `_track_why(item)` | Accept `PhaseItem`; use `item.tracks_why` instead of `item.phase.tracks_why`; access `item.work_item.resolved_version`, `item.work_item.req_type`, `item.work_item.req` |
| `_record_stack_state(stack)` | Accept `list[PhaseItem]`; replace `[serialize(item) for item in reversed(stack)]` with `[item.as_json() for item in reversed(stack)]` — remove the inline `serialize()` helper entirely |
| `_handle_phase_error(item, err)` | Replace `item.phase == BootstrapPhase.RESOLVE` checks with `isinstance(item, ResolveItem)` etc.; replace phase-mutation fallback with `ProcessInstallDepsItem(item.work_item)` construction (see Error handling); update all `item.*` attribute accesses to `item.work_item.*` (see Attribute migration below) |
| `_create_unresolved_work_items(...)` | Return `list[ResolveItem]` instead of `list[WorkItem]`; remove `phase=BootstrapPhase.RESOLVE` from `WorkItem(...)` constructor; wrap each result: `ResolveItem(WorkItem(...))` |
| `bootstrap()` | Remove `phase=BootstrapPhase.RESOLVE` from `WorkItem(...)` calls; wrap each in `ResolveItem(WorkItem(...))` |
| `_bootstrap_one()` | Same — remove `phase=` from `WorkItem(...)`, wrap in `ResolveItem(WorkItem(...))` |
| `_run_bootstrap_loop(stack)` | Accept `list[PhaseItem]`; change `it.phase == BootstrapPhase.RESOLVE` progress-bar check to `isinstance(it, ResolveItem)`; change `self.why = list(item.why_snapshot)` to `self.why = list(item.work_item.why_snapshot)`; change `req_ctxvar_context(item.req, item.resolved_version)` to `req_ctxvar_context(item.work_item.req, item.work_item.resolved_version)` |

#### Attribute migration in `Bootstrapper` methods

After the refactor, `item` parameters that were `WorkItem` become `PhaseItem`. All attribute accesses must be updated:

| Old (`WorkItem`) | New (`PhaseItem`) |
| -- | -- |
| `item.phase` | `type(item).phase` (ClassVar — still accessible on instance, but explicit is clearer) |
| `item.req` | `item.work_item.req` |
| `item.req_type` | `item.work_item.req_type` |
| `item.resolved_version` | `item.work_item.resolved_version` |
| `item.source_url` | `item.work_item.source_url` |
| `item.pbi_pre_built` | `item.work_item.pbi_pre_built` |
| `item.build_result` | `item.work_item.build_result` |
| `item.why_snapshot` | `item.work_item.why_snapshot` |
| `item.bg_future` | `item.bg_future` (moved to `PhaseItem` base — no change) |

This applies to `_handle_phase_error`, `_run_bootstrap_loop`, `_track_why`, and any other `Bootstrapper` method that receives a `PhaseItem`. Inside each `PhaseItem.run()` method, references to the old `self` (Bootstrapper) become `bt` and references to the old `item.*` become `self.work_item.*`.

#### `StartItem.run()` mutation ordering

`StartItem.run()` must set `self.work_item.build_sdist_only` and `self.work_item.pbi_pre_built` **before** constructing `PrepareSourceItem(self.work_item)`, because `PrepareSourceItem.background_work(bt)` reads `work_item.pbi_pre_built` to choose between `_bg_prepare_source` and `_bg_prepare_prebuilt`:

```python
# Inside StartItem.run():
self.work_item.build_sdist_only = (
    bt.sdist_only and not bt._processing_build_requirement(self.work_item.req_type)
)
self.work_item.pbi_pre_built = bt.ctx.package_build_info(self.work_item.req).pre_built
# Now safe to hand work_item to the next phase:
return [PrepareSourceItem(self.work_item)]
```

### Error handling

`_handle_phase_error` uses `isinstance` checks:

```python
if isinstance(item, ResolveItem): ...
if isinstance(item, (PrepareSourceItem, PrepareBuildItem, BuildItem)): ...
```

The test-mode prebuilt fallback currently mutates `item.phase` before returning:

```python
# Old: mutation
item.build_result = fallback
item.phase = BootstrapPhase.PROCESS_INSTALL_DEPS
return [item]
```

With `PhaseItem` classes this must instead construct a new item:

```python
# New: construction
item.work_item.build_result = fallback
return [ProcessInstallDepsItem(item.work_item)]
```

## Files to Modify

- `src/fromager/bootstrapper.py` — all changes (primary file)
- `tests/test_bootstrapper.py` — update affected tests

## Test Changes

- `test_phase_build_produces_source_build_result`:

  - Replace `WorkItem(phase=BootstrapPhase.BUILD, ...)` construction with `BuildItem(WorkItem(...))` (no `phase=` arg)
  - Change `bt._phase_build(item)` → `item.run(bt)` inside the `bt._track_why(item)` context
  - Change `result_items[0].phase == BootstrapPhase.PROCESS_INSTALL_DEPS` → `isinstance(result_items[0], ProcessInstallDepsItem)`

- `_make_resolve_item()` helper:

  - Remove `phase=BootstrapPhase.RESOLVE` from `WorkItem(...)` call
  - Wrap result in `ResolveItem`: `return ResolveItem(WorkItem(...))`
  - Update return type annotation from `bootstrapper.WorkItem` to `bootstrapper.ResolveItem`
  - Update all callers that compare `item.phase` directly to use `type(item).phase` or `isinstance(item, ResolveItem)`

- `_record_and_load()` helper:

  - Change parameter type annotation from `list[bootstrapper.WorkItem]` to `list[bootstrapper.PhaseItem]`

- `test_record_stack_state_full_item`:

  - Replace `WorkItem(phase=BootstrapPhase.BUILD, ...)` with `BuildItem(WorkItem(...))` (remove `phase=` arg)

- `test_record_stack_state_dep_sets_are_sorted`:

  - Replace `WorkItem(phase=BootstrapPhase.BUILD, ...)` with `BuildItem(WorkItem(...))` (remove `phase=` arg)

- `test_multiple_versions_continues_on_error` and similar tests that check `item.phase in (BootstrapPhase.RESOLVE, BootstrapPhase.START, ...)` inside mock dispatchers:

  - Replace phase equality checks with `isinstance(item, (ResolveItem, StartItem, ...))`

- Tests for `_handle_phase_error`:

  - Any test that constructs a mid-pipeline `WorkItem` (e.g. with `phase=PREPARE_SOURCE`) and passes it to `_handle_phase_error` must instead construct the corresponding `PhaseItem` subclass (e.g. `PrepareSourceItem(WorkItem(...))`)
  - Tests that check the prebuilt fallback return value must assert `isinstance(result[0], ProcessInstallDepsItem)` rather than checking a mutated `WorkItem.phase`

- All remaining tests that import or reference `WorkItem` with a `phase=` keyword argument must drop the `phase=` argument

## New Tests

These test cases do not exist yet and should be added to cover the new class hierarchy and changed method behaviors.

### `PhaseItem` base class

- `test_phase_item_str_default` — `str(BuildItem(work_item))` returns `"BuildItem(<req>)"` using the default `__str__` implementation.
- `test_phase_item_background_work_returns_none_by_default` — phases that do not override `background_work()` (`PrepareBuildItem`, `BuildItem`, `ProcessInstallDepsItem`, `CompleteItem`) return `None`.

### Class variable correctness

- `test_phase_class_variables` — parametrize over all 7 subclasses; assert `MyClass.phase == expected_phase` and `MyClass.tracks_why == expected_bool` as listed in the design table. Verifies that class-variable declarations are not accidentally overridden by instance state.

### `background_work()` dispatch

- `test_resolve_item_background_work_returns_callable` — `ResolveItem(work_item).background_work(bt)` returns a non-`None` callable (does not call it; just verifies a callable is produced).
- `test_prepare_source_item_background_work_source` — when `work_item.pbi_pre_built=False`, `PrepareSourceItem.background_work(bt)` returns a callable that wraps `_bg_prepare_source`.
- `test_prepare_source_item_background_work_prebuilt` — when `work_item.pbi_pre_built=True`, `PrepareSourceItem.background_work(bt)` returns a callable that wraps `_bg_prepare_prebuilt`.

### `StartItem` mutation ordering

- `test_start_item_sets_pbi_pre_built_before_constructing_prepare_source` — `StartItem.run(bt)` must set `work_item.pbi_pre_built` before the returned `PrepareSourceItem` is constructed, so that `PrepareSourceItem.background_work(bt)` immediately sees the correct value. Verify by checking `result[0].work_item.pbi_pre_built` is set correctly and that calling `result[0].background_work(bt)` (with the same bootstrapper) returns the appropriate callable branch.

### Phase advancement shares `work_item` identity

- `test_phase_advancement_preserves_work_item_identity` — when `BuildItem(wi).run(bt)` returns `[ProcessInstallDepsItem(...)]`, assert `result[0].work_item is wi` (same object, not a copy). Applies to any phase that returns the next phase wrapping the same `work_item`.

### `CompleteItem`

- `test_complete_item_run_returns_empty_list` — `CompleteItem(work_item).run(bt)` returns `[]`.

### `_dispatch_phase` delegation

- `test_dispatch_phase_calls_item_run` — `bt._dispatch_phase(item)` calls `item.run(bt)` and returns its result without a `match/case` block. Patch `item.run` to return a sentinel list and assert the sentinel is returned.

### `_track_why` with `PhaseItem`

- `test_track_why_not_pushed_for_no_tracks_why_item` — inside `bt._track_why(resolve_item)`, `bt.why` is not modified (because `ResolveItem.tracks_why` is `False`).
- `test_track_why_pushed_for_tracks_why_item` — inside `bt._track_why(build_item)`, `bt.why` gains one entry while in the context and is restored on exit (because `BuildItem.tracks_why` is `True`).

### `_push_items` background future submission

- `test_push_items_sets_bg_future_when_pool_exists` — construct a `Bootstrapper` with a live `ThreadPoolExecutor` as `_bg_pool`; call `_push_items` with a `ResolveItem`; assert `item.bg_future` is not `None` after the call.
- `test_push_items_no_bg_future_when_pool_is_none` — when `bt._bg_pool` is `None`, calling `_push_items` with a `ResolveItem` leaves `item.bg_future` as `None`.

### `as_json()` phase field per subclass

- `test_as_json_phase_field_per_subclass` — parametrize over all 7 `(SubclassType, BootstrapPhase)` pairs; construct the subclass wrapping a minimal `WorkItem` and assert `item.as_json()["phase"] == str(expected_phase)`. Guards against a subclass accidentally inheriting the wrong `phase` ClassVar or the serialization using a stale field.

### `_create_unresolved_work_items` return type

- `test_create_unresolved_work_items_returns_resolve_items` — the returned items are `ResolveItem` instances (not bare `WorkItem` objects). Each `item.work_item` holds the expected `req` and `req_type`.

## Verification

```bash
# After each phase class is extracted:
hatch run mypy:check src/fromager/bootstrapper.py
hatch run test:test tests/test_bootstrapper.py

# Full check at the end:
hatch run lint:fix src/fromager/bootstrapper.py tests/test_bootstrapper.py
hatch run mypy:check src/fromager/bootstrapper.py
hatch run test:test tests/test_bootstrapper.py
hatch run lint:check src/fromager/bootstrapper.py
```

## Implementation Order

1. Add `abc` import; define `PhaseItem` abstract base class above `Bootstrapper`
2. Create each concrete subclass one at a time, moving `_phase_*` body into `run()`:
   a. `ResolveItem` (with `background_work()` override)
   b. `StartItem`
   c. `PrepareSourceItem` (with `background_work()` override)
   d. `PrepareBuildItem`
   e. `BuildItem`
   f. `ProcessInstallDepsItem`
   g. `CompleteItem`
3. Update `WorkItem`: remove `phase` and `bg_future` fields
4. Update `Bootstrapper`: remove deleted methods, simplify `_dispatch_phase`, `_push_items`, `_track_why`, `_record_stack_state`, `_handle_phase_error`, `_create_unresolved_work_items`, `bootstrap()`, `_bootstrap_one()`
5. Update `tests/test_bootstrapper.py`
6. Run full verification
