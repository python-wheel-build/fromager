Protect Against Supply-Chain Attacks with PyPI Cooldown
========================================================

Fromager's PyPI cooldown policy rejects package versions that were published
fewer than a configured number of days ago. This protects automated builds from
supply-chain attacks where a malicious version is published and immediately
pulled in before it can be reviewed.

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

Use the global ``--pypi-min-age`` flag, or set the equivalent environment
variable ``FROMAGER_PYPI_MIN_AGE``:

.. code-block:: bash

   # Reject versions published in the last 7 days
   fromager --pypi-min-age 7 bootstrap -r requirements.txt

   # Same, via environment variable (useful for CI and builder integrations)
   FROMAGER_PYPI_MIN_AGE=7 fromager bootstrap -r requirements.txt

   # Disable the cooldown (default)
   fromager --pypi-min-age 0 bootstrap -r requirements.txt

The ``--pypi-min-age`` flag accepts a non-negative integer number of days.
A value of ``0`` (the default) disables the check entirely.

Scope
-----

The cooldown applies only to **sdist resolution** — selecting which version of a
package to build from source, including transitive dependencies. It does not
apply to:

* Wheel-only lookups, including cache servers (``--cache-wheel-server-url``) and
  packages configured as ``pre_built: true`` in variant settings. These use a
  different trust model and are not subject to the cooldown regardless of which
  server they are fetched from.
* Packages resolved from Git URLs, which use a separate code path.

Note that sdist resolution from a private package index depends on
``upload-time`` being present in the index's PEP 691 JSON responses. If the
index does not provide that metadata, candidates will be rejected under the
fail-closed policy described below.

Explicit version pins (``package==1.2.3``) are subject to the same cooldown as
unpinned requirements. If the pinned version was published within the cooldown
window, resolution will fail. To unblock a specific run, set ``--pypi-min-age 0``
or use the environment variable.

Fail-Closed Behavior
--------------------

If a candidate has no ``upload-time`` metadata — which can occur with older
PyPI Simple HTML responses — it is rejected when a cooldown is active. Fromager
uses the `PEP 691 JSON Simple API`_ when fetching package metadata, which
reliably includes upload timestamps.

.. _PEP 691 JSON Simple API: https://peps.python.org/pep-0691/

Example
-------

Given a package ``example-pkg`` with three available versions:

* ``2.0.0`` — published 3 days ago
* ``1.9.0`` — published 45 days ago
* ``1.8.0`` — published 120 days ago

With a 7-day cooldown, ``2.0.0`` is blocked and ``1.9.0`` is selected:

.. code-block:: bash

   fromager --pypi-min-age 7 bootstrap example-pkg

With a 60-day cooldown, both ``2.0.0`` and ``1.9.0`` are blocked and ``1.8.0``
is selected:

.. code-block:: bash

   fromager --pypi-min-age 60 bootstrap example-pkg

Overriding the Cooldown for a Pinned Version
--------------------------------------------

If a pinned version is blocked by the cooldown, resolution fails with a message
identifying the cause:

.. code-block:: console

   $ fromager --pypi-min-age 7 bootstrap example-pkg==2.0.0
   ERROR: found 1 candidate(s) for example-pkg==2.0.0 but all were published
          within the last 7 days (PyPI cooldown; oldest is 3 day(s) old)

To override the cooldown for a single run, set ``--pypi-min-age 0``:

.. code-block:: bash

   fromager --pypi-min-age 0 bootstrap example-pkg==2.0.0

A value of ``0`` disables the cooldown entirely, allowing any version to be
selected regardless of when it was published.
