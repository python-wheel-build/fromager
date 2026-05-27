# Pluggable sandboxing API for external commands

- Author: Christian Heimes, Pavan Kalyan
- Created: 2026-05-26
- Status: Open
- Issue: [#1019](https://github.com/python-wheel-build/fromager/issues/1019)

## What

A plugin API for running external processes that lets users plug in different
sandboxing solutions.

## Why

Sandboxing prevents build processes from modifying the host system, reading
sensitive data, or interfering with other packages. On Linux, Fromager has
simple network isolation with `unshare`. Users need the ability to plug in
their own sandboxing configuration to confine build processes with tools like
[bubblewrap](https://github.com/containers/bubblewrap),
[firejail](https://github.com/netblue30/firejail),
[Landlock](https://landlock.io/integrations/) /
[Landlock API](https://docs.kernel.org/userspace-api/landlock.html), or
container runtimes.

## Goals

- Platform-agnostic API that supports a wide range of sandboxing tools and
  that does not assume a specific OS, container runtime, or privilege level.
- Life cycle hooks to set up and tear down persistent sandboxing environments

## Non-goals

- Implementing sandboxing beyond the current network isolation. Sandboxing is
  hard to get right and there are many existing tools to choose from. Fromager
  should delegate to those tools rather than re-implement confinement.

## How

### Hooks

Four hooks in global settings control sandboxing:

```yaml
external_commands:
  setup_sandbox: fromager.external_commands:default_setup_sandbox
  teardown_sandbox: fromager.external_commands:default_teardown_sandbox
  run_sandboxed: fromager.external_commands:default_run_sandboxed
  run_unconfined: fromager.external_commands:default_run_unconfined
```

All four hooks require `ctx`, `req`, and `sdist_root_dir` keyword arguments.

The `run_sandboxed` and `run_unconfined` hooks accept a subset of
[`subprocess.run`](https://docs.python.org/3/library/subprocess.html#subprocess.run)
keyword arguments (`stdin`, `stdout`, `stderr`, `cwd`, `timeout`, `text`,
`env`) and return a `subprocess.CompletedProcess` object.

The `run_unconfined` hook is included so users can monitor and police
unconfined calls.

### Life cycle

`setup_sandbox` runs after the `prepare_source` hook and before sdists and
wheels are built. `teardown_sandbox` runs after `build_wheel`. These hooks
exist for sandboxing solutions that require persistent state across multiple
commands, such as creating namespaces, mounting filesystems, or adjusting
file permissions.

The sandbox is set up and torn down for each package+version
combination. A failed `setup_sandbox` aborts the build.
`teardown_sandbox` always runs (via `finally`) regardless of build
success or failure.

### Writable directories and isolation

Only `sdist_root_dir.parent` (`work-dir/{name}-{version}`) should be
writable. Sandboxing tools may create `tmp` and `home` subdirectories
there for persistent temporary or home directories (e.g. XDG cache or
config directories).

The `build_sdist` and `build_wheel` hooks should write output to
`sdist_root_dir.parent / "dist"`. Fromager will create this directory
before the build and move the resulting files into the correct location
afterwards. When moving output files, fromager must verify they are
regular files and not symlinks or other special files (e.g. device
nodes, FIFOs) to prevent symlink escape attacks where a build creates
a symlink pointing outside the sandbox boundary.

The `pyproject_hooks` library communicates with build backends via
temporary files. These IPC files must be inside the writable
`sdist_root_dir.parent` directory, not in `/tmp`, so that sandbox
hooks can give each build a private `/tmp` without breaking the IPC
channel.

Other shared state like writing to the Fromager installation, modifying
the host OS, or using shared caches like ccache, sccache, or the Rust
cache defeats the purpose of sandboxing and isolation between builds.

### API changes

- `BuildEnvironment` gains `req` and `sdist_root_dir` arguments
- New methods: `BuildEnvironment.run_sandboxed`,
  `WorkContext.run_sandboxed`, `WorkContext.run_unconfined`
- `external_commands.run()` becomes internal (should no longer be used by
  external code)
- `BuildEnvironment.run` is deprecated and will eventually be removed

`BuildEnvironment.run_unconfined` is intentionally omitted until there is a
valid use case.

### CLI migration

`--network-isolation` becomes an alias for `--enable-sandbox` /
`--disable-sandbox`. The existing network isolation feature stays as the
default sandboxing implementation.

## Sandboxing considerations

When implementing a sandbox hook, consider the following threat
vectors (see [#1019] for the full analysis):

- **Credential access:** Build backends can read files like
  `$HOME/.netrc` or environment variables containing tokens
  (`GITHUB_TOKEN`, `GITLAB_PRIVATE_TOKEN`, `NGC_API_KEY`, etc.).
  Hide the user's home directory (e.g. mount a tmpfs over `$HOME`)
  and scrub sensitive variables from the build environment.
- **Network access:** A build can exfiltrate stolen data or
  download payloads. Block network access entirely and configure
  only a loopback device.
- **Process and IPC visibility:** Builds can enumerate processes
  via `/proc` or interfere through shared memory and semaphores.
  Isolate PID, IPC, and UTS namespaces.
- **Persistence:** A malicious build can leave backdoors (`.pth`
  files, shell profile entries, background daemons) that affect
  every subsequent build. Make `/usr`, `/var`, the fromager
  installation, and settings directories read-only. Only
  `sdist_root_dir.parent` should be writable.
- **Shared temporary directories:** Parallel builds sharing `/tmp`
  can interfere with each other. Give each sandbox a private `TMP`,
  `HOME`, and `XDG` directories.
- **Untrusted source tree:** Sdist contents are untrusted. Tar
  unpacking should block device files, FIFOs, and the setuid bit.
  Mount the source tree (`sdist_root_dir`) with `nodev` and
  `nosuid` as an additional safeguard.
- **Syscall filtering:** Even inside namespaces, a build process can
  attempt dangerous syscalls (`ptrace`, `mount`, `personality`,
  `keyctl`). Consider restricting syscalls with seccomp-bpf where
  the sandbox tool supports it (nsjail, firejail).
- **Resource exhaustion:** A malicious build can fork-bomb, exhaust
  memory, or fill writable directories. Apply cgroups or rlimits
  to constrain CPU, memory, and process count. Tools like nsjail
  and systemd-run support this; bubblewrap and Landlock do not.

Available tools each cover a different subset of these vectors:

| Tool | Filesystem | Network | PID/IPC | Needs root | Notes |
| -- | -- | -- | -- | -- | -- |
| `unshare` | No | Yes | Yes | No | Current default; works in unprivileged Podman |
| bubblewrap | Yes | Yes | Yes | In containers | Requires `CAP_SYS_ADMIN` inside containers |
| firejail | Yes | Yes | Yes | No | Feature-rich; available on most distributions |
| Landlock | Yes | Yes (6.7+) | Partial (6.11+) | No | Filesystem since 5.13, TCP since 6.7, signal/socket scoping since 6.11 |
| systemd-run | Yes | Yes | Yes | No | Requires systemd as PID 1 |
| nsjail | Yes | Yes | Yes | No | Namespaces + cgroups + seccomp |

No single tool covers all deployment models (root in a container,
unprivileged user on a workstation, CI without root). The pluggable
hook API lets each deployment choose the appropriate solution.

## Future work

Fromager may ship hook implementations for popular sandboxing tools such as
bubblewrap, firejail, or Podman in the future.

[#1019]: https://github.com/python-wheel-build/fromager/issues/1019
