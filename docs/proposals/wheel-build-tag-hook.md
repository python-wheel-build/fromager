# Unique wheel file names with a `wheel_build_tag` hook

- Author: Christian Heimes
- Created: 2026-04-16
- Status: Open
- GitHub issue: [#1059](https://github.com/python-wheel-build/fromager/issues/1059)

## What

This enhancement proposes a new configurable hook, `build_tag_hook`, for
injecting custom suffixes into the
[wheel build tag](https://packaging.python.org/en/latest/specifications/binary-distribution-format/),
producing unique wheel file names that encode platform, accelerator stack,
and dependency ABI information.

## Why

Fromager-built wheels are platform-specific and may depend on:

- **OS / distribution version**, e.g. Fedora 43, RHEL 9.6, RHEL 10.1
- **AI accelerator stack**, e.g. CUDA 13.1 vs CUDA 12.9, ROCm 7.1
- **Torch ABI**, which is unstable across versions; a wheel compiled for
  Torch 2.10.0 may have a different ABI than one compiled for Torch 2.11.0

Currently, wheel filenames carry none of this information, making it
difficult to invalidate caches, distinguish builds for different stacks, or
replace outdated wheels with correctly-targeted rebuilds.

## Goals

- introduce a `build_tag_hook` option in the `wheels` section of the global
  settings file
- allow the hook to contribute ordered suffix segments to the wheel build tag
- produce unique, deterministic wheel file names that reflect the build
  environment

## Non-goals

- Filtering or selecting wheels by build tag at install time. `pip install`
  and `uv pip install` only use the build tag for sorting, not for filtering.
- Sharing wheels across indexes. While unique file names enable this in
  principle, the mechanics of cross-index sharing are out of scope.
- Accessing wheel content, the build environment, or ELF dependency info from
  within the hook. The hook must work identically whether a wheel is freshly
  built or retrieved from cache.
- Validation of annotations such as "depends on libtorch". A validation
  system for `build_wheel` may be added in the future.
- Package override hook. It would complicate the design and there is no
  compelling use-case for package-specific tags.

## How

### Wheel spec background

The wheel filename format is:

```
{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
```

The [build tag](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
is optional, must start with a digit, and must not contain `-`. Fromager
already fills the numeric part from the variant + package changelog and sets
the string suffix to `""`. This proposal extends that suffix with
hook-provided segments (e.g. `_el9.6_rocm7.1_torch2.10.0`).

### Configuration

The hook is configured in the global settings file under a new `wheels`
section. The callable is specified as a dotted import path using Pydantic's
`ImportString` type for validation and loading.

```yaml
wheels:
  build_tag_hook: "mypackage.hooks:build_tag_hook"
```

When `build_tag_hook` is not set, no suffix is appended to the build tag.

### Hook signature

```python
def build_tag_hook(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    wheel_tags: frozenset[Tag],
) -> typing.Sequence[str]: ...
```

The hook returns `typing.Sequence[str]`, a sequence of suffix segments
(e.g. `["el9.6", "rocm7.1", "torch2.10.0"]`). The segments are joined
with `_` and appended to the existing build tag.

Each segment must only contain alphanumeric ASCII characters or dot
(`[a-zA-Z0-9.]`). When the hook returns any other character or raises an
exception, the build fails.

### Example hook

```{literalinclude} wheel_tag_example_hook.py
:start-at: example_hook
```

### Hook scope

The hook can access `ctx` (variant, package settings, annotations),
`wheel_tags` (to distinguish purelib vs platlib), and standard library
APIs like `os.environ` and `platform.freedesktop_os_release()`.

The hook **cannot** access wheel content, the build environment, or ELF
dependency info. These are unavailable when wheels come from cache, and the
hook must produce the same result regardless of source.

### Examples

| Wheel | Build tag | OS | Stack |
| -- | -- | -- | -- |
| `flash_attn-2.8.3-8_el9.6_rocm7.1_torch2.10.0-cp312-cp312-linux_x86_64.whl` | `8_el9.6_rocm7.1_torch2.10.0` | RHEL 9.6 | ROCm |
| `torch-2.10.0-7_el9.6_rocm7.1-cp312-cp312-linux_x86_64.whl` | `7_el9.6_rocm7.1` | RHEL 9.6 | ROCm |
| `torch-2.9.1-8_fc43_cuda13.0-cp312-cp312-linux_x86_64.whl` | `8_fc43_cuda13.0` | Fedora 43 | CUDA |
| `pillow-12.2.0-2_el9.6-cp312-cp312-linux_x86_64.whl` | `2_el9.6` | RHEL 9.6 | any |
| `fromager-0.79.0-2-py3-none-any.whl` | `2` (no suffix) | any | any |

Pure-python wheels (`py3-none-any`) receive no suffix, while platlib wheels
get progressively more specific tags based on their dependencies.

## Limitations

A single index still cannot contain both CUDA and ROCm builds of the same
package. `pip` and `uv` only use the build tag for sorting, not filtering.
The upcoming [Wheel.Next](https://wheelnext.dev/) initiative
([PEP 817](https://peps.python.org/pep-0817/) /
[PEP 825](https://peps.python.org/pep-0825/)) aims to address this with
wheel variants. Hook logic for accelerator selection may be reusable when
that standard lands.
