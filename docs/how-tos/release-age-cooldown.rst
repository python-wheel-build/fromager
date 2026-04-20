Protect Against Supply-Chain Attacks with Release-Age Cooldown
==============================================================

Fromager's release-age cooldown policy rejects package versions that were
published fewer than a configured number of days ago. This protects automated
builds from supply-chain attacks where a malicious version is published and
immediately pulled in before it can be reviewed.

How It Works
------------

When a cooldown is active, any candidate whose ``upload-time`` is more recent
than the cutoff (current time minus the configured minimum age) is not
considered a valid option during constraint resolution. If no versions of a
package satisfy both the cooldown window and any other provided constraints,
resolution fails with an informative error.

The cutoff timestamp is fixed at the start of each run, so all package
resolutions within a single bootstrap share the same boundary.

Enabling the Cooldown
---------------------

Use the global ``--min-release-age`` flag, or set the equivalent environment
variable ``FROMAGER_MIN_RELEASE_AGE``:

.. code-block:: bash

   # Reject versions published in the last 7 days
   fromager --min-release-age 7 bootstrap -r requirements.txt

   # Same, via environment variable (useful for CI and builder integrations)
   FROMAGER_MIN_RELEASE_AGE=7 fromager bootstrap -r requirements.txt

   # Disable the cooldown (default)
   fromager --min-release-age 0 bootstrap -r requirements.txt

The ``--min-release-age`` flag accepts a non-negative integer number of days.
A value of ``0`` (the default) disables the check entirely.

Scope
-----

The cooldown applies to both **sdist resolution** and **pre-built wheel
resolution** — any candidate whose ``upload-time`` is more recent than the
cutoff is rejected, regardless of whether it is an sdist or a prebuilt wheel.

The following are **not** subject to the cooldown:

* Fromager's internal build and cache wheel servers. These are not used for
  version selection — they are checked only for already-resolved pinned
  versions — so the cooldown has no insertion point.
* Packages resolved from Git URLs. Git timestamps are set by the client, not
  the server, and cannot be trusted for cooldown enforcement.

Resolution from a private package index (sdist or wheel) depends on
``upload-time`` being present in the index's PEP 691 JSON responses. If the
index does not provide that metadata, candidates are rejected under the
fail-closed policy described below. Use ``resolver_dist.min_release_age: 0``
to bypass cooldown for packages from indexes that structurally cannot supply
timestamps.


Fail-Closed Behavior
--------------------

If a candidate has no ``upload-time`` metadata — whether it is an sdist or a
wheel — it is rejected when a cooldown is active. Fromager uses the
`PEP 691 JSON Simple API`_ when fetching package metadata, which reliably
includes upload timestamps for PyPI.org.

.. _PEP 691 JSON Simple API: https://peps.python.org/pep-0691/

For indexes that only implement the `PEP 503`_ HTML API and cannot supply
timestamps, use the per-package ``resolver_dist.min_release_age: 0`` override
to bypass the cooldown for affected packages rather than disabling it globally.

.. _PEP 503: https://peps.python.org/pep-0503/

.. note::

   If you are writing a ``get_resolver_provider`` plugin that uses
   :class:`~fromager.resolver.PyPIProvider` with a private index that only
   implements the PEP 503 HTML API, pass ``supports_upload_time=False`` to
   ``PyPIProvider``. This switches the provider from fail-closed to
   warn-and-skip, so candidates without upload timestamps are skipped with a
   warning rather than causing resolution to fail.

Example
-------

Given a package ``example-pkg`` with three available versions:

* ``2.0.0`` — published 3 days ago
* ``1.9.0`` — published 45 days ago
* ``1.8.0`` — published 120 days ago

With a 7-day cooldown, ``2.0.0`` is blocked and ``1.9.0`` is selected:

.. code-block:: bash

   fromager --min-release-age 7 bootstrap example-pkg

With a 60-day cooldown, both ``2.0.0`` and ``1.9.0`` are blocked and ``1.8.0``
is selected:

.. code-block:: bash

   fromager --min-release-age 60 bootstrap example-pkg

Per-Package Override
--------------------

The cooldown can be adjusted on a per-package basis using the
``resolver_dist.min_release_age`` setting in the package's settings file:

.. code-block:: yaml

   # overrides/settings/my-package.yaml
   resolver_dist:
     min_release_age: 0   # disable cooldown for this package
     # min_release_age: 30  # or use a different number of days

Valid values:

* Omit the key (default): inherit the global ``--min-release-age`` setting.
* ``0``: disable the cooldown for this package, regardless of the global flag.
* Positive integer: use this many days instead of the global setting.

This is useful when a specific package is trusted enough to allow recent
versions, or when a package's release cadence makes the global cooldown
impractical.
