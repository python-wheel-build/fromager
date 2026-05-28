# fromager

Fromager is a tool for rebuilding complete dependency trees of Python
wheels from source.

## Goals

Fromager is designed to guarantee that:

- Every binary package you install was built from source in a reproducible environment compatible with your own.

- All dependencies are also built from source, no prebuilt binaries.

- The build tools themselves are built from source, ensuring a fully transparent toolchain.

- Builds can be customized for your needs: applying patches, adjusting compiler options, or producing build variants.

## Design Principles

Fromager automates the build process with sensible defaults that work for most PEP-517–compatible packages. At the same time, every step can be overridden for special cases, without baking those exceptions into Fromager itself.

## Build Collections of Wheels

Fromager can also build wheels in collections, rather than individually. Managing dependencies as a unified group ensures that:

- Packages built against one another remain ABI-compatible.

- All versions are resolved consistently, so the resulting wheels can be installed together without conflicts.

This approach makes Fromager especially useful in Python-heavy domains like AI, where reproducibility and compatibility across complex dependency trees are essential.

## Authentication

Fromager automatically authenticates to GitHub and GitLab APIs using
credentials from netrc or environment variables. See the
[authentication guide](docs/how-tos/authentication.md) for details.

## Additional docs

- [Using fromager](docs/using.md)
- [Package build customization instructions](docs/customization.md)
- [Developer instructions](docs/develop.md)

## What's with the name?

Python's name comes from Monty Python, the group of comedians. One of
their skits is about a cheese shop that has no cheese in stock. The
original Python Package Index (pypi.org) was called The Cheeseshop, in
part because it hosted metadata about packages but no actual
packages. The wheel file format was selected because cheese is
packaged in wheels. And
"[fromager](https://en.wiktionary.org/wiki/fromager)" is the French
word for someone who makes or sells cheese.
