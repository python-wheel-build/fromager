# Build isolation for sandboxing build backends

- Author: Pavan Kalyan Reddy Cherupally
- Created: 2026-04-21
- Status: Open
- Issue: [#1019](https://github.com/python-wheel-build/fromager/issues/1019)

## What

A `--build-isolation` flag that sandboxes PEP 517 build backend
subprocesses (`build_sdist`, `build_wheel`) so they cannot read
credentials, access the network, or interfere with the host system.

## Why

Fromager executes upstream-controlled code (setup.py, build backends)
during wheel builds. A compromised or malicious package can:

- Read credential files like `$HOME/.netrc` and exfiltrate tokens
- Reach the network to upload stolen data or download payloads
- Signal or inspect other processes via `/proc` or shared IPC
- Interfere with parallel builds through shared `/tmp`
- Leave persistent backdoors: `.pth` files that run on every Python
  startup, shell profile entries that run on every login, or
  background daemons that survive the build

The existing `--network-isolation` flag blocks network access but does
not protect against credential theft, process/IPC visibility, or
persistent backdoors.

Network isolation alone is insufficient — a build can embed stolen
credentials in the wheel itself, bypassing network controls when the
wheel is distributed. Persistence attacks are especially dangerous
because fromager builds many packages sequentially: a single
malicious package can compromise every subsequent build through
`.pth` files, a poisoned `pip.conf`, a tainted compiler cache, or a
background daemon.

## Goals

- A `--build-isolation/--no-build-isolation` CLI flag (default off)
- `--build-isolation` supersedes `--network-isolation` — it applies
  to the same build steps but adds credential, process/IPC, and
  persistence protection on top of network isolation
- Only PEP 517 hook calls are sandboxed; download, dependency
  installation, and upload steps run without isolation (same scope
  as `--network-isolation` today)
- Works in unprivileged Podman containers without `--privileged`
  or `--cap-add SYS_ADMIN`. Docker requires a seccomp profile that
  permits `unshare`. On Ubuntu 24.04,
  `sysctl kernel.apparmor_restrict_unprivileged_userns=0` is needed.

## Non-goals

- **Mount namespace isolation.** Breaks `pyproject_hooks` IPC, which
  exchanges `input.json`/`output.json` through `/tmp`.
- **macOS / Windows support.** Linux-only; flag is unavailable on
  other platforms.

## How

Each PEP 517 hook invocation is wrapped in two layers of isolation:

1. **Ephemeral Unix user** — a short-lived system user
   (`fmr_<random>`) created with `useradd` and removed on exit.
   The user has no home directory and no login shell, so it cannot
   read root-owned credential files (mode 600). Requires fromager
   to run as root inside the container; when running as non-root,
   namespace isolation still applies but credential and persistence
   protection are not available.

2. **Linux namespace isolation** — `unshare` places the build in
   new network (no routing), PID (own process tree), IPC (own
   shared memory), and UTS (separate hostname) namespaces. This
   extends the existing `run_network_isolation.sh` wrapper, which
   only uses network and UTS namespaces.

### Limitations

- **SIGKILL / OOM kill**: ephemeral user cleanup runs in a
  `trap EXIT` handler, which is not triggered by `SIGKILL` or
  OOM kills. Long bootstrap runs could accumulate orphaned
  `fmr_*` entries in `/etc/passwd`.

- **Build cache poisoning**: the ephemeral user still needs write
  access to the build directory, so cache poisoning is not fully
  addressed. Fixing this would require mount namespace isolation,
  which is incompatible with the `pyproject_hooks` IPC mechanism
  (see Non-goals).

## Examples

```bash
fromager --build-isolation bootstrap -r requirements.txt
```

## Findings

A proof-of-concept package
([build-attack-test](https://github.com/pavank63/build-attack-test))
validates the attack surface by running security probes from
`setup.py` during build hooks.

| Attack vector | `--network-isolation` | `--build-isolation` |
| -- | -- | -- |
| Credential file access (`.netrc`) | **Vulnerable** | Blocked |
| Network access | Blocked | Blocked |
| Process visibility (PID) | **Vulnerable** | Blocked |
| IPC (shared memory, semaphores) | **Vulnerable** | Blocked |
| Hostname leakage | **Vulnerable** | Blocked |
| Shared cache/config access | **Vulnerable** | Partial (see Limitations) |
| Persistent backdoors (`.pth`, shell profiles, daemons) | **Vulnerable** | Blocked |
