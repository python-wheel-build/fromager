Enable Repeatable Builds
========================

There are times we need to ensure that the bootstrap process does not change the
packages to the latest versions on its own. Instead, we want to use the last
stable bootstrap as the only source of truth to ensure that the build process is
fully repeatable and predictable. Moreover, we also want to allow upgrading of
specific packages to rebuild new RC blockers, do bug fixes, etc.

Fromager supports repeatable builds to ensure the bootstrap process does not
pull unnecessary new dependencies when they are not required. It uses the output
files of previous successful bootstrap to avoid these dependency updates.

The bootstrap command of fromager has an option `--previous-bootstrap-file`
which can be used to achieve repeatable builds. The user needs to set the file
path for `graph.json` from the latest stable bootstrap for the above option. The
example bootstrap command to use repeatable builds is as follows:

.. code-block:: bash

   fromager bootstrap --previous-bootstrap-file=path/to/graph.json -r path/to/requirements.txt

For the above example, replace `path/to/graph.json` with an actual path to
`graph.json` file and `path/to/requirements.txt` with an actual path to
`requirements.txt` file.
