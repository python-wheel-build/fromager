# Upstream and downstream source provenance

- Author: Lalatendu Mohanty
- Created: 2026-08-06
- Status: Open
- Issue: [#1296](https://github.com/python-wheel-build/fromager/issues/1296)
  (child of [#1238](https://github.com/python-wheel-build/fromager/issues/1238))

## Prerequisite

This proposal assumes that Fromager builds wheels from the verified downstream
sdist. The current implementation builds the wheel from the mutable prepared
source tree, which may be modified during sdist creation—for example, by
adding `PKG-INFO`.

This is tracked separately in
[#1311](https://github.com/python-wheel-build/fromager/issues/1311) and should
be resolved before implementing this proposal. Otherwise, the recorded
downstream sdist cannot be treated as the authoritative input to the wheel.

## What

Record where every build came from and what happened to its source.

An sdist build has two different source artifacts:

```text
upstream archive or Git checkout
              │
              ▼
       prepared source tree
              │
              ▼
       downstream sdist
              │
              ▼
             wheel
```

For the upstream input, record its source and the exact bytes used. For the
prepared source, record the changes made by Fromager and its plugins. For the
downstream sdist and wheel, record the resulting bytes and their relationship
to the upstream input.

For a pre-built package, record the upstream wheel and its digest. SHA-256 is
used to identify the bytes.

The complete record lives in `provenance-index.json`. `graph.json` and
`build-order.json` keep the artifact information needed by the build and
references to the complete record.

The first implementation phase is capture-only. It records the current
unpack, repack, and `PKG-INFO` behavior without changing build results.

## Why

Fromager’s current sdist flow has several gaps:

- It unpacks and repacks sdists. The downstream tarball usually has a
  different digest from the upstream archive, but that relationship is not
  recorded clearly.
- It records URLs and versions, but not the exact upstream file that was
  consumed. This is especially important for Git sources because a tag can
  move.
- It does not record the changes or digest of the downstream sdist well
  enough to validate reuse.
- Some plugins produce different sdists for different variants, platforms, or
  build environments. The cause of that difference is not recorded.
- Git and raw-tarball sources may not contain usable `PKG-INFO`. Fromager may
  add a stub, but the origin of that metadata is not recorded.

Without this information, a build cannot answer which source produced a wheel
or explain why two sdists for the same package and version differ.

Index digests, such as PyPI file hashes, help verify an upstream download.
They do not describe source changes or identify the downstream sdist.

## Goals

- Record the complete lineage of every build.
- Preserve the exact upstream archive or Git source used.
- Record Git repository, requested ref/tag, resolved commit, and source-tree
  identity when the input comes from Git.
- Record unpacking, repacking, patches, vendoring, overrides, plugin changes,
  and `PKG-INFO` changes.
- Record a digest of the prepared source tree, downstream sdist, and wheel.
- Record normalized build context so variant-specific outputs are explainable.
- Make it possible to verify and safely reuse an sdist or cache entry.
- Keep artifact identity separate from mirror and package-index locations.
- Preserve existing plugin boundaries and path-based APIs.

## Non-goals

- Changing the default unpack-and-repack sdist behavior.
- Generating correct `PKG-INFO` for Git or raw-tarball sources.
- Attestation retrieval or verification in the first version.
- Attestation documents, signing, or key management.
- Hash algorithms other than SHA-256.
- Authenticating VCS checkouts or plugin transformations.
- Verifying a locally built wheel against an external digest.

The first version records the current sdist and `PKG-INFO` behavior. A later
proposal may change how sdists or metadata are generated.

## How

### Architecture overview

Provenance becomes a shared capability across the build pipeline. The complete
record has one owner. Existing pipeline files carry small projections.

```text
source provider ──► resolver ──► build context ──► provenance store
      │                 │              │                  │
      │                 │              │                  ├─ full lineage
      │                 │              │                  └─ schema version
      │                 │              │
      │                 │              └─ build context and source changes
      │                 │
      │                 └─ source identity and expected digest
      │
      └─ optional upstream evidence

build context ──► acquire ──► prepare ──► sdist ──► wheel
                  observed    changes     output     output
                  digest                 digest     digest
```

The work is divided into three implementation phases. Each phase leaves the
previous phase's records usable.

### Phase 1 — Capture build lineage

Phase 1 answers: “Which upstream bytes, source changes, downstream sdist, and
wheel produced this build?” It does not change how Fromager builds packages.
It records observed digests but does not reject artifacts based on them.

#### Provenance records

Use a small set of related records:

- `SourceIdentity` identifies an upstream source according to how it was
  acquired: as a file or from a version-control system.
- `ArtifactRecord` describes one file input or output artifact, including its
  role, source, filename, expected digest, observed digest, digest source, and
  verification status.
- `TransformationRecord` describes one source or metadata change, such as a
  patch, repack, vendoring step, or generated `PKG-INFO`.
- `SourceLineage` connects the upstream inputs, ordered transformations,
  build context, prepared source tree, and output artifacts for one build.
- `BuildContext` records the variant, platform, Python build interpreter, build
  settings, plugin identities, and controlling configuration digests.

File artifacts use a typed content identity: artifact type, digest algorithm,
and observed digest. A VCS source uses a separate typed identity containing the
repository, requested ref, resolved commit, root tree identity, and resolved
submodule commits. The VCS identifiers are not file SHA-256 values. Artifact
role, URLs, filenames, and package metadata describe the source or its use but
do not replace its identity.

This allows a Git checkout to be recorded without inventing a file digest, and
allows an upstream sdist and a repacked downstream sdist to have the same
filename without being confused with each other. A source materialized both as
a VCS checkout and as an archive records those as separate identities.

#### Upstream input

An upstream input is the source that Fromager actually consumes.

For an archive or raw tarball, record:

- the origin URL and effective URL;
- the filename and artifact type; and
- the expected digest, if a trusted source supplied one, and the observed
  digest of the downloaded bytes.

For a Git source, record:

- the repository URL;
- the requested tag, branch, or ref;
- the resolved commit; and
- the checked-out tree identity, including relevant submodules.

The tag or branch is a locator, not the source identity. The resolved commit,
root tree identity, and submodule commits form the immutable VCS input
identity. If the commit cannot be resolved, the lineage is partial or
unverified. The resolved source identity must remain attached to the selected
source as it moves through resolution, acquisition, and preparation.

For a generated sdist, record the repository, ref, or source archive as the
upstream input and record the generated sdist as a separate output. An
upstream archive digest never verifies the generated output. For a pre-built
wheel, the wheel is the upstream input and there is no downstream sdist.

#### Plugin-generated sources

Existing path-returning plugin APIs remain supported. Fromager records the
returned artifact, its digest, and the plugin identity. Plugins and shared
helpers may also register contributing inputs and transformations, including
VCS commits and submodules. Without that information, lineage is partial; a
final path, filename, or digest alone does not prove the source history.

#### Source changes and build context

Record the ordered changes between the upstream input and the prepared source
tree. This includes unpacking, repacking, patches, project overrides,
vendoring, plugin changes, and metadata changes.

Record whether `PKG-INFO` was:

- present in the upstream source;
- generated by a build backend; or
- added as a Fromager stub.

Record a normalized build context with the values that can affect the output:

- Fromager variant;
- target platform;
- Python implementation and version used to run the build, including ABI or
  free-threaded mode when it can affect the output;
- relevant build settings;
- plugin identities; and
- digests of controlling configuration.

The build interpreter is distinct from the Python compatibility tags recorded
in a wheel's metadata. Do not record the interpreter executable path because
it is machine-specific.

Do not capture arbitrary environment variables or secrets. If a plugin changes
the source in a way that cannot be described, record the plugin identity and
prepared-tree digest and mark the lineage partial.

#### Downstream artifacts

The downstream sdist is a new artifact, even when it has the same filename as
the upstream source. Record its filename, observed digest, metadata status,
build context, and `derived_from` link to the upstream input.

Record the wheel as a build output with its observed digest and a
`derived_from` link to the downstream sdist.

This makes the normal repack operation visible:

```text
upstream sdist digest ≠ downstream sdist digest
                         │
                         └─ both remain in the same lineage
```

An sdist may have a different digest for a different variant or build context.
That is a distinct output lineage, not an unexplained replacement.

The downstream artifact record must remain associated with the persisted sdist
so a later build can find and validate it. A filename alone is not enough to
identify reusable provenance.

#### Provenance storage

`provenance-index.json` is the canonical audit record. It is keyed by package
and version and allows multiple lineages for the same key.

Its essential shape is:

```json
{
  "schema_version": 1,
  "builds": {
    "package==1.0": [
      {
        "lineage_id": "package==1.0:source",
        "inputs": ["upstream_input:file:sha256:<digest>"],
        "transformations": ["patch:<digest>", "pkg-info:generated-stub"],
        "build_context": "<normalized-context-digest>",
        "prepared_tree_sha256": "<digest>",
        "outputs": [
          "downstream_sdist:file:sha256:<digest>",
          "build_output:file:sha256:<digest>"
        ],
        "lineage_status": "complete"
      }
    ]
  }
}
```

The actual records also contain package metadata, filenames, source
references, expected digests, observed digests, and verification status. The
example shows the relationships that matter most.

`graph.json` and `build-order.json` remain operational files. They contain the
selected artifact identity, applicable digest information, and stable
`artifact_id`/`lineage_id` references. They do not duplicate the full
transformation history or artifact records.

The same provenance capture path is used by iterative bootstrap, `build`,
`step`, `download-sequence`, and other source-build drivers. Builder-managed
downloaders and shared source helpers use the plugin registration channel so
their upstream inputs and generated outputs receive the same treatment.

### Phase 2 — Verify and safely reuse artifacts

Phase 2 uses the lineage captured in Phase 1 to decide whether an artifact can
be trusted or reused.

#### Resolution and acquisition

The resolver passes a resolved artifact containing the source, artifact type,
filename, and applicable expected digest. The build context carries it into
source preparation and build steps.

All artifact inputs use one digest-aware acquisition boundary:

- new downloads are hashed while they are read;
- existing files and cache entries are hashed before reuse; and
- URL, index, lock-file, and continuity expectations are checked.

A known mismatch is an error, not a cache miss. Existing path-returning
download and plugin APIs remain available through compatibility adapters.

Expected and observed digests have different meanings:

- `expected_sha256` is a trusted claim about the selected artifact;
- `sha256` is calculated from bytes Fromager accepts or produces.
- `digest_source` identifies where the expected value came from, such as an
  index, URL fragment, lock file, or previous provenance record.

Conflicting claims are errors. An artifact without a trusted expectation is
recorded as observed or unverified, not as cryptographically verified.

#### Safe reuse and failure behavior

Downstream sdist reuse requires both:

- a matching sdist digest; and
- lineage metadata showing that it came from the current source changes and
  build context.

If the metadata is missing or stale, Fromager rebuilds the sdist. An explicit
legacy import may reuse it, but the resulting lineage is marked partial.

Invalid digest values are input errors. A known mismatch fails a normal build.
Test mode may continue collecting independent package failures, but an
integrity failure is recorded separately, does not trigger pre-built fallback,
and makes the final result fail.

### Phase 3 — Integrate consumers and upstream evidence

Optional upstream evidence may be attached to an upstream artifact when it is
already available from a provider or source integration. Examples include:

- attestation availability or a reference to an attestation;
- publisher and repository;
- workflow;
- ref and commit;
- release date; and
- wheel tags.

This evidence is informational in v1. Fromager does not fetch or verify
attestations as part of this proposal.

An optional `PublicationRecord` describes an artifact copied to a source
mirror or published to a package index. It includes the publication location
and digest of the published bytes. A publication never replaces the upstream
URL, effective source, or lineage relationship.

The builder onboarder must preserve the upstream URL and digest, preserve any
genuine downstream sdist identity, and record an uploaded upstream copy as a
source-mirror publication. It must detect a conflicting remote file by digest,
not filename alone.

It must update build-order and provenance data as one consistent generation.
The upstream URL and expected/observed digest remain separate from the
downstream sdist filename and digest. A mirror URL must never replace the
upstream identity.

### Future work — Improve sdist quality

The following changes are intentionally outside this proposal’s first three
phases because they change build behavior:

- avoid unnecessary sdist repacking where possible;
- generate correct `PKG-INFO` for Git and raw-tarball sources; and
- make sdist generation deterministic across variants and environments where
  practical.

The first three phases record the current behavior so a later proposal can
change it safely.

## Backward compatibility

Older `graph.json` and `build-order.json` files remain loadable. Missing
metadata is recorded as unverified; it is not upgraded to a trusted
expectation.

Older downstream sdists are not eligible for automatic lineage-aware reuse.
They are rebuilt by default, or explicitly imported as partial lineage.

Existing path-returning download helpers and plugin signatures remain
available. Digest-aware behavior is added behind internal adapters.

No package settings changes are required for the initial design. The new
provenance file and graph/build-order fields are versioned and documented.

## Rollout and testing

Implement the design in the following phases:

1. **Capture lineage** — Add the provenance records. Capture archive and Git
   input identity, source changes, `PKG-INFO` status, normalized build
   context, prepared-tree digest, downstream sdist, wheel, and lineage links.
   Write `provenance-index.json` and references in graph/build-order files.
2. **Verify and reuse safely** — Add expected-versus-observed digest checks,
   cache verification, continuity checks, and lineage-aware downstream sdist
   reuse. Fail closed on integrity mismatches.
3. **Integrate consumers** — Update builder onboarding and capture optional
   upstream evidence when supplied by existing integrations. Update the
   builder pin.

Improving sdist generation remains a separate follow-up proposal.

Tests should verify the core invariants:

- an upstream archive and repacked downstream sdist retain separate digests;
- moving a Git tag is detected through the resolved commit and tree identity;
- source changes and `PKG-INFO` status are recorded;
- variant and platform changes produce explainable lineages;
- cache and existing-file verification fail closed;
- generated and VCS sources support complete or partial lineage;
- graph/build-order references round-trip without duplicating the full record;
- optional upstream evidence is preserved without being treated as verified;
  and
- builder mirror publication behavior preserves artifact identity.
